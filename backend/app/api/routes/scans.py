"""Submit photographs of a package and get back what the rules make of them."""

from __future__ import annotations

import logging
from datetime import date
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool

from app.api.deps import ADMIN, AnyOfficer, DbSession, WritableDb
from app.core.db import utcnow
from app.models.enums import Channel, FindingStatus, ImageKind, Verdict
from app.pipeline.scale import COIN_MM
from app.rules.loader import ruleset_by_version, ruleset_for_date
from app.schemas.auth import OverrideRequest
from app.schemas.scan import (
    DeleteScanRequest,
    RetentionRequest,
    ScanPageOut,
    ScanResultOut,
    ScanSummaryOut,
)
from app.services import audit, persistence, retention, scanning, storage
from app.services.imaging import MAX_IMAGES, ScanInputError, decode

log = logging.getLogger(__name__)

router = APIRouter(prefix="/scans", tags=["scans"])


def _kinds_for(images: list[UploadFile], raw: str | None) -> list[str]:
    """Which face of the pack each photograph shows.

    Defaults to FRONT for the first and SIDE for the rest, which is what a hurried
    field capture actually is. The kind is metadata for the officer and for report
    layout; no rule is decided differently because of it.
    """
    if not raw:
        return [ImageKind.FRONT.value] + [ImageKind.SIDE.value] * (len(images) - 1)

    kinds = [k.strip().upper() for k in raw.split(",")]
    if len(kinds) != len(images):
        raise ScanInputError(
            f"{len(kinds)} image kinds were given for {len(images)} images."
        )
    valid = {k.value for k in ImageKind}
    for kind in kinds:
        if kind not in valid:
            raise ScanInputError(
                f"{kind!r} is not a kind of image; expected one of {sorted(valid)}."
            )
    return kinds


async def _accept(
    images: list[UploadFile],
    *,
    kinds: str | None,
    coin: str | None,
) -> list[scanning.SubmittedImage]:
    """Validate and decode an upload. Shared by the preview and the stored path."""
    if not images:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Submit at least one photograph.")
    if len(images) > MAX_IMAGES:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"{len(images)} images were submitted; at most {MAX_IMAGES} can be scanned at once.",
        )
    if coin is not None and coin not in COIN_MM:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"{coin!r} is not a coin this server knows; expected one of {sorted(COIN_MM)}.",
        )

    try:
        kind_list = _kinds_for(images, kinds)
        submitted = []
        for upload, kind in zip(images, kind_list, strict=True):
            data = await upload.read()
            submitted.append(
                scanning.SubmittedImage(
                    image_id=scanning.new_image_id(),
                    image=decode(
                        data, filename=upload.filename, content_type=upload.content_type
                    ),
                    kind=kind,
                    filename=upload.filename,
                )
            )
    except ScanInputError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return submitted


@router.post(
    ":analyze",
    response_model=ScanResultOut,
    summary="Scan a package against the Legal Metrology rules in force",
    status_code=status.HTTP_200_OK,
)
async def analyze(
    images: Annotated[list[UploadFile], File(description="Photographs of the package.")],
    channel: Annotated[Channel, Form()] = Channel.PHYSICAL,
    is_imported: Annotated[bool, Form()] = False,
    category: Annotated[str | None, Form()] = None,
    is_raised: Annotated[bool, Form()] = False,
    scan_date: Annotated[date | None, Form()] = None,
    coin: Annotated[str | None, Form()] = None,
    kinds: Annotated[str | None, Form()] = None,
) -> ScanResultOut:
    """Judge one package.

    `scan_date` selects the ruleset in force on that date, so a 2019 pack is not judged
    against the Unit Sale Price rule that arrived in 2022. It defaults to today.

    There is deliberately no way to supply a scale. Millimetre findings require a
    fiducial of known size in the frame — the printable ArUco card, an ID-1 card or a
    ₹5/₹10 coin. Without one, Rule 8 findings come back NEEDS_REVIEW rather than
    measured, and no parameter on this endpoint can change that.
    """
    submitted = await _accept(images, kinds=kinds, coin=coin)

    # OCR is seconds of CPU. Off the event loop, or one scan stalls every other request.
    return await run_in_threadpool(
        scanning.analyse,
        submitted,
        channel=channel,
        is_imported=is_imported,
        category=category,
        is_raised=is_raised,
        scan_date=scan_date,
        coin=coin,
    )


# --------------------------------------------------------------------- the repository


@router.post(
    "",
    response_model=ScanResultOut,
    summary="Scan a package and file the result",
    status_code=status.HTTP_201_CREATED,
)
async def create_scan(
    images: Annotated[list[UploadFile], File(description="Photographs of the package.")],
    product_name: Annotated[str, Form(min_length=1, max_length=255)],
    db: WritableDb,
    officer: AnyOfficer,
    brand: Annotated[str | None, Form()] = None,
    category: Annotated[str | None, Form()] = None,
    gtin: Annotated[str | None, Form()] = None,
    channel: Annotated[Channel, Form()] = Channel.PHYSICAL,
    is_imported: Annotated[bool, Form()] = False,
    is_raised: Annotated[bool, Form()] = False,
    scan_date: Annotated[date | None, Form()] = None,
    coin: Annotated[str | None, Form()] = None,
    kinds: Annotated[str | None, Form()] = None,
    latitude: Annotated[float | None, Form()] = None,
    longitude: Annotated[float | None, Form()] = None,
    place_name: Annotated[str | None, Form()] = None,
    notes: Annotated[str | None, Form()] = None,
) -> ScanResultOut:
    """Judge one package and keep the record: images, extractions, findings.

    The response is read back out of the database rather than returned from memory, so
    what the officer is shown now is exactly what they will see when they reopen the
    scan later. A divergence between the two is the kind of thing nobody notices until
    a report is challenged.

    The scan is attributed to the signed-in officer. An inspection record with no
    inspector on it is not an inspection record.
    """
    submitted = await _accept(images, kinds=kinds, coin=coin)

    outcome, ruleset = await run_in_threadpool(
        scanning.run,
        submitted,
        channel=channel,
        is_imported=is_imported,
        category=category,
        is_raised=is_raised,
        scan_date=scan_date,
        coin=coin,
    )

    product = persistence.find_or_create_product(
        db,
        name=product_name,
        brand=brand,
        category=category,
        gtin=gtin,
        is_imported=is_imported,
        created_by=officer,
    )
    scan = persistence.save_scan(
        db,
        outcome,
        ruleset,
        submitted,
        product=product,
        created_by=officer,
        latitude=latitude,
        longitude=longitude,
        place_name=place_name,
        notes=notes,
    )
    audit.record(
        db,
        action=audit.Action.SCAN_FILED,
        entity_type="scan",
        entity_id=scan.id,
        actor=officer,
        after={
            "product_id": product.id,
            "verdict": str(scan.verdict),
            "ruleset_version": scan.ruleset_version,
        },
    )
    db.commit()

    stored = persistence.load_scan(db, scan.id)
    assert stored is not None  # just committed in this session
    return persistence.to_response(stored, ruleset)


@router.get("", response_model=ScanPageOut, summary="Search filed scans")
def search_scans(
    db: DbSession,
    officer: AnyOfficer,
    verdict: Annotated[Verdict | None, Query()] = None,
    product_id: Annotated[str | None, Query()] = None,
    rule_id: Annotated[
        str | None, Query(description="Only scans that FAILED this rule.")
    ] = None,
    since: Annotated[date | None, Query()] = None,
    include_deleted: Annotated[
        bool, Query(description="Include soft-deleted scans in the results.")
    ] = False,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ScanPageOut:
    from app.models.enums import FindingStatus
    from app.rules.engine import coverage
    from app.rules.schema import FindingResult

    scans, total = persistence.list_scans(
        db,
        verdict=verdict,
        product_id=product_id,
        rule_id=rule_id,
        since=since,
        limit=limit,
        offset=offset,
        include_deleted=include_deleted,
    )

    summaries = []
    for scan in scans:
        decided, applicable = coverage(
            [
                FindingResult(
                    rule_id=f.rule_id,
                    title=f.title,
                    citation=f.citation,
                    status=f.status,
                    severity=f.severity,
                    message=f.message,
                )
                for f in scan.findings
            ]
        )
        summaries.append(
            ScanSummaryOut(
                scan_id=scan.id,
                product_id=scan.product_id,
                product_name=scan.product.name if scan.product else None,
                scan_date=scan.scan_date,
                created_at=scan.created_at,
                verdict=scan.verdict or Verdict.INCONCLUSIVE,
                score=scan.compliance_score,
                rules_decided=decided,
                rules_applicable=applicable,
                failed=sum(1 for f in scan.findings if f.status is FindingStatus.FAIL),
                needs_review=sum(
                    1 for f in scan.findings if f.status is FindingStatus.NEEDS_REVIEW
                ),
                ruleset_version=scan.ruleset_version,
                case_open=scan.case_open,
                eligible_for_deletion=retention.describe(
                    scan, retention.effective_retention_days(db)
                ).eligible_for_deletion,
                deleted=scan.deleted_at is not None,
            )
        )
    return ScanPageOut(total=total, limit=limit, offset=offset, scans=summaries)


@router.get("/{scan_id}", response_model=ScanResultOut, summary="One filed scan")
def get_scan(scan_id: str, db: DbSession, officer: AnyOfficer) -> ScanResultOut:
    scan = persistence.load_scan(db, scan_id)
    if scan is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No scan {scan_id!r}.")

    # Reopened against the ruleset that judged it, not today's. A finding must always
    # be readable against the rules it was actually decided under.
    try:
        ruleset = ruleset_by_version(scan.ruleset_version or "")
    except KeyError:
        log.warning(
            "Scan %s cites ruleset %r, which is no longer on disk; reading it against "
            "the set in force on its scan date instead.",
            scan.id, scan.ruleset_version,
        )
        ruleset = ruleset_for_date(scan.scan_date)
    return persistence.to_response(scan, ruleset)


@router.get(
    "/{scan_id}/images/{image_id}",
    summary="An evidence image, as submitted",
    response_class=FileResponse,
)
def get_scan_image(scan_id: str, image_id: str, db: DbSession, officer: AnyOfficer):
    """Serve one stored photograph.

    The image is looked up through its scan rather than by key, so a caller cannot ask
    for an arbitrary storage path — and a finding's evidence stays reachable, which is
    what makes a FAIL something an officer can check rather than take on trust.
    """
    scan = persistence.load_scan(db, scan_id)
    if scan is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No scan {scan_id!r}.")

    image = next((i for i in scan.images if i.id == image_id), None)
    if image is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No image {image_id!r} on this scan.")

    try:
        path = storage.path_of(image.storage_key)
    except storage.StorageError as exc:
        raise HTTPException(status.HTTP_410_GONE, str(exc)) from exc
    return FileResponse(path, media_type="image/png", filename=f"{image_id}.png")


# ------------------------------------------------------------------------- override


OVERRIDABLE = (FindingStatus.PASS, FindingStatus.FAIL, FindingStatus.NEEDS_REVIEW)


# ------------------------------------------------------------------------ retention


@router.post(
    "/{scan_id}/retention",
    response_model=ScanResultOut,
    summary="Record whether a case is still open on this scan",
)
def set_retention(
    scan_id: str, body: RetentionRequest, db: WritableDb, officer: AnyOfficer
) -> ScanResultOut:
    """Answer the one question that governs deletion: is a case still open?

      * True  — the scan is kept indefinitely. It is never auto-deleted, whatever its
        age or verdict. A COMPLIANT scan flagged this way (a repeat-inspection
        baseline, say) is retained the same as any other.
      * False — the scan becomes eligible for auto-deletion once the retention window
        has passed *from now*, not from when the scan was filed. Changing the answer
        later restarts that clock.

    Not calling this endpoint leaves the answer unset, and an unreviewed scan is never
    eligible for deletion. Silence is not consent.

    Every call is audit-logged with the previous answer and the new one.
    """
    scan = persistence.load_scan(db, scan_id)
    if scan is None or scan.deleted_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No scan {scan_id!r}.")

    retention.record_decision(db, scan, body.case_open, officer)
    db.commit()

    reopened = persistence.load_scan(db, scan_id)
    assert reopened is not None
    try:
        ruleset = ruleset_by_version(reopened.ruleset_version or "")
    except KeyError:
        ruleset = ruleset_for_date(reopened.scan_date)
    return persistence.to_response(reopened, ruleset)


# -------------------------------------------------------------------- manual delete


@router.delete(
    "/{scan_id}",
    response_model=ScanResultOut,
    summary="Soft-delete a scan",
)
def delete_scan(
    scan_id: str,
    db: WritableDb,
    officer: AnyOfficer,
    body: DeleteScanRequest | None = None,
) -> ScanResultOut:
    """Remove a scan from the working repository without destroying it.

    Soft delete only: the row, its images and its findings stay in the database and the
    removal is written to the audit trail, so the scan's existence and the fact it was
    deleted remain accountable.

      * An officer may delete a scan they filed. An administrator may delete any scan.
      * A case being open does **not** block a manual delete. That is an explicit
        decision by an authorised person; only the scheduled auto-deletion job defers
        to `case_open`.
    """
    scan = persistence.load_scan(db, scan_id)
    if scan is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No scan {scan_id!r}.")
    if scan.deleted_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "This scan is already deleted.")
    if officer.role != ADMIN and scan.created_by_id != officer.id:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "You can only delete scans you filed; ask an administrator to delete this one.",
        )

    retention.soft_delete(
        db, scan, actor=officer, reason=body.reason if body else None, automated=False
    )
    db.commit()

    reopened = persistence.load_scan(db, scan_id)
    assert reopened is not None
    try:
        ruleset = ruleset_by_version(reopened.ruleset_version or "")
    except KeyError:
        ruleset = ruleset_for_date(reopened.scan_date)
    return persistence.to_response(reopened, ruleset)


@router.post(
    "/{scan_id}/findings/{rule_id}:override",
    response_model=ScanResultOut,
    summary="Record an officer's decision over an automated finding",
)
def override_finding(
    scan_id: str,
    rule_id: str,
    body: OverrideRequest,
    db: WritableDb,
    officer: AnyOfficer,
) -> ScanResultOut:
    """Set a finding to what the officer decided, without losing what the machine did.

    The machine's verdict moves to `original_status` and stays there. It is returned in
    every later response alongside the officer's, and the change is written to the audit
    log with the reason. Three things this endpoint will not do:

      * It will not overwrite an existing `original_status`. A second override records
        the officer's new decision against the *machine's* original, so a chain of
        revisions can never quietly erase where it started.
      * It will not accept NA. Whether a rule applies is a question about the statute
        and the package, not a judgement call — an officer who thinks a rule should not
        apply is describing an exemption, which is a change to the ruleset.
      * It will not recompute the score. The score summarises what the rules decided;
        an officer's decision is recorded next to it, not blended into it.
    """
    scan = persistence.load_scan(db, scan_id)
    if scan is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No scan {scan_id!r}.")
    if scan.deleted_at is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This scan has been deleted; its findings cannot be overridden.",
        )

    finding = next((f for f in scan.findings if f.rule_id == rule_id), None)
    if finding is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"Scan {scan_id!r} has no finding for rule {rule_id!r}."
        )

    try:
        decided = FindingStatus(body.status)
    except ValueError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"{body.status!r} is not a finding status; expected one of "
            f"{', '.join(s.value for s in OVERRIDABLE)}.",
        ) from exc

    if decided not in OVERRIDABLE:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "A finding cannot be overridden to NA. Whether a rule applies to a package "
            "is a matter of the rules and any exemption, not an officer's discretion.",
        )
    if finding.status is FindingStatus.NA:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"{rule_id} did not apply to this package, so there is no finding to overrule.",
        )
    if decided is finding.status:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"{rule_id} is already {decided.value}. An override records a disagreement.",
        )

    before = {"status": finding.status.value, "original_status": (
        finding.original_status.value if finding.original_status else None
    )}
    # Set only on the first override, so the machine's verdict is what is preserved
    # rather than whatever the previous officer decided.
    if finding.original_status is None:
        finding.original_status = finding.status
    finding.status = decided
    finding.override_reason = body.reason
    finding.overridden_by_id = officer.id
    finding.overridden_at = utcnow()

    audit.record(
        db,
        action=audit.Action.FINDING_OVERRIDDEN,
        entity_type="finding",
        entity_id=finding.id,
        actor=officer,
        before=before,
        after={
            "scan_id": scan_id,
            "rule_id": rule_id,
            "status": decided.value,
            "original_status": finding.original_status.value,
            "reason": body.reason,
        },
    )
    db.commit()

    reopened = persistence.load_scan(db, scan_id)
    assert reopened is not None
    try:
        ruleset = ruleset_by_version(reopened.ruleset_version or "")
    except KeyError:
        ruleset = ruleset_for_date(reopened.scan_date)
    return persistence.to_response(reopened, ruleset)
