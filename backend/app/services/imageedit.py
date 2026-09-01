"""Editing a filed scan's photographs, and re-judging it from the new set.

The rule this module exists to enforce: findings never outlive the evidence they were
read from. An officer who deletes a blurred photograph and retakes it has changed what
the pack looks like to the system, and a violation still standing on screen from the
discarded frame is worse than no finding at all — it is a finding the current evidence
does not support.

So every image change re-runs the pipeline over the whole current set. Not a status
flag, not a partial patch: the images are read back off disk and put through OCR, scale
recovery, measurement and the rule engine exactly as a fresh submission would be. That
is slower, and it is the only way the findings can be trusted to describe the
photographs actually on file.

What is deliberately not carried across a re-run: officer overrides. An override is a
judgement about one finding read from one set of photographs — "the second price is a
promotional sticker, I checked the pack". Re-applying it to a finding derived from
different evidence would carry a human decision onto something it was never made
about. The override, its reason and its author are preserved in the revision snapshot;
the officer is asked to decide again against what the scan now says.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import cv2
from sqlalchemy.orm import Session

from app.models.enums import Channel, ScanStatus, Verdict
from app.models.tables import ExtractedField, Finding, Scan, ScanImage, ScanRevision, User
from app.rules.loader import ruleset_by_version, ruleset_for_date
from app.services import audit, persistence, scanning, storage

log = logging.getLogger(__name__)

# A scan must keep at least one photograph. A scan with no images is not a scan whose
# declarations are all missing — it is a record with no evidence at all.
MIN_IMAGES = 1


class ImageEditError(RuntimeError):
    """The edit cannot be made. Carries a message fit to show an officer."""


@dataclass(frozen=True)
class Edit:
    """What changed, for the audit log and the revision reason."""

    action: str  # IMAGE_ADDED / IMAGE_REMOVED / IMAGE_REPLACED
    reason: str  # "image added" / "image removed" / "image replaced"
    detail: str


def ruleset_for(scan: Scan):
    """The ruleset that judged this scan, so a re-run is not silently re-dated.

    Re-photographing a pack does not change which rules were in force when it was
    inspected. Falling back to today's set would let an edit quietly move a 2019 scan
    onto rules that did not exist then.
    """
    try:
        return ruleset_by_version(scan.ruleset_version or "")
    except KeyError:
        log.warning(
            "Scan %s cites ruleset %r, which is no longer on disk; re-judging against "
            "the set in force on its scan date.",
            scan.id,
            scan.ruleset_version,
        )
        return ruleset_for_date(scan.scan_date)


def snapshot(db: Session, scan: Scan, edit: Edit, actor: User) -> ScanRevision:
    """Freeze what the scan currently says, before the re-run replaces it."""
    revision = ScanRevision(
        scan_id=scan.id,
        revision=scan.revision,
        reason=edit.reason,
        detail=edit.detail,
        snapshot=persistence.to_response(scan, ruleset_for(scan)).model_dump(mode="json"),
        superseded_by_id=actor.id,
    )
    db.add(revision)
    return revision


def load_images(scan: Scan) -> list[scanning.SubmittedImage]:
    """Read the current image set back off disk, keeping each image's identity.

    Image ids are preserved so a finding's evidence still points at the photograph it
    was read from — a re-run must not renumber the evidence.
    """
    loaded: list[scanning.SubmittedImage] = []
    for row in scan.images:
        try:
            path = storage.path_of(row.storage_key)
        except storage.StorageError as exc:
            raise ImageEditError(
                f"The photograph {row.id[:8]} is no longer in the store, so this scan "
                "cannot be re-judged. Its findings are unchanged."
            ) from exc
        image = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if image is None or image.size == 0:
            raise ImageEditError(
                f"The photograph {row.id[:8]} could not be decoded, so this scan cannot "
                "be re-judged. Its findings are unchanged."
            )
        loaded.append(
            scanning.SubmittedImage(
                image_id=row.id,
                image=image,
                kind=str(row.kind),
                filename=row.original_filename,
            )
        )
    return loaded


def reevaluate(db: Session, scan: Scan) -> None:
    """Re-run the whole pipeline over the scan's current photographs.

    Everything derived from the images is discarded and rebuilt: extracted fields,
    findings, the scale, the panel area, the verdict and the score. Nothing is patched
    in place, because a partial update is how a finding from a discarded frame
    survives.
    """
    images = load_images(scan)
    if not images:
        raise ImageEditError("A scan must keep at least one photograph.")

    outcome, _ = scanning.run(
        images,
        channel=Channel(scan.channel),
        is_imported=scan.product.is_imported if scan.product else False,
        category=scan.product.category if scan.product else None,
        scan_date=scan.scan_date,
    )

    # Clear everything derived from images. Overrides go with them, by design.
    for field_row in list(scan.fields):
        db.delete(field_row)
    for finding_row in list(scan.findings):
        db.delete(finding_row)
    db.flush()

    scale = outcome.scale
    scan.mm_per_px = scale.mm_per_px
    scan.scale_source = str(scale.source)
    scan.scale_confidence = scale.confidence
    scan.scale_detail = scale.detail
    scan.pdp_area_cm2 = outcome.pdp_area_cm2
    scan.panel_method = outcome.panel_method
    scan.exemption_id = outcome.exemption_id
    scan.pipeline_notes = list(outcome.notes)
    scan.compliance_score = outcome.compliance_score
    scan.verdict = Verdict(outcome.verdict)
    scan.extractor_version = outcome.extractor_version
    scan.status = ScanStatus.COMPLETE

    blocks: dict[str, list] = {}
    for block in outcome.ocr_blocks:
        blocks.setdefault(block.image_id or "", []).append(
            {"text": block.text, "polygon": block.polygon, "confidence": block.confidence}
        )
    for image_row in scan.images:
        image_row.ocr_blocks = blocks.get(image_row.id, [])

    for value in outcome.fields.values():
        db.add(
            ExtractedField(
                scan_id=scan.id,
                field_key=value.key,
                raw_text=value.raw_text,
                normalized=value.parsed.as_dict() if value.parsed is not None else None,
                confidence=value.confidence,
                source_image_id=value.image_id,
                bbox=value.bbox,
                glyph_height_mm=value.glyph_height_mm,
                glyph_width_mm=value.glyph_width_mm,
            )
        )
    for result in outcome.findings:
        db.add(
            Finding(
                scan_id=scan.id,
                rule_id=result.rule_id,
                title=result.title,
                citation=result.citation,
                status=result.status,
                severity=result.severity,
                message=result.message,
                remediation=result.remediation,
                detail=result.detail or {},
                evidence_bbox=result.evidence_bbox,
                evidence_image_id=result.evidence_image_id,
            )
        )
    db.flush()

    # Expire the collections this function just replaced.
    #
    # Sessions here are created with expire_on_commit=False, so a commit does not
    # invalidate what is already loaded. Without this the deleted ExtractedField and
    # Finding objects stay in `scan.fields` / `scan.findings` in memory, a later
    # selectinload returns the cached collection rather than re-querying, and the
    # response is built from the reading that was just superseded — the pipeline
    # having genuinely re-run and produced the right answer the whole time.
    db.expire(scan, ["fields", "findings", "images"])

    log.info("Scan %s re-judged from %d photograph(s): %s", scan.id, len(images), scan.verdict)


def apply(db: Session, scan: Scan, edit: Edit, actor: User) -> None:
    """Snapshot, re-run, bump the revision, and write the audit entry."""
    overrides_cleared = sum(1 for f in scan.findings if f.original_status is not None)
    before = {
        "revision": scan.revision,
        "verdict": str(scan.verdict),
        "score": scan.compliance_score,
        "images": len(scan.images),
        "officer_decisions_cleared": overrides_cleared,
    }

    snapshot(db, scan, edit, actor)
    scan.revision += 1
    reevaluate(db, scan)

    audit.record(
        db,
        action=edit.action,
        entity_type="scan",
        entity_id=scan.id,
        actor=actor,
        before=before,
        after={
            "revision": scan.revision,
            "verdict": str(scan.verdict),
            "score": scan.compliance_score,
            "images": len(scan.images),
            "detail": edit.detail,
        },
    )


def find_image(scan: Scan, image_id: str) -> ScanImage:
    image = next((i for i in scan.images if i.id == image_id), None)
    if image is None:
        raise ImageEditError(f"This scan has no photograph {image_id!r}.")
    return image
