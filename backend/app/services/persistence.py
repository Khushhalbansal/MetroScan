"""Write a scan to the database, and read one back as the same shape.

The important structural choice here: after a scan is saved, the API response is
rebuilt *from the stored rows* rather than from the in-memory outcome. It costs a
round trip and it is worth it — otherwise POST returns what the pipeline produced and
GET returns what the database kept, the two drift, and the divergence shows up as an
officer opening a saved report that disagrees with the one they were shown. Reading
back through one function means the round trip is exercised on every single scan.

Nothing here re-decides anything. Statuses, scores and verdicts are stored exactly as
the engine produced them.
"""

from __future__ import annotations

import logging
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.models.enums import FindingStatus, Severity, Verdict
from app.models.tables import ExtractedField, Finding, Product, Scan, ScanImage, User
from app.pipeline.runner import ScanOutcome
from app.rules.engine import coverage
from app.rules.engine import score as compute_score
from app.rules.engine import verdict as compute_verdict
from app.rules.schema import FindingResult, RuleSet
from app.schemas.scan import (
    AssessmentOut,
    CalibrationOut,
    EvidenceOut,
    FieldOut,
    FindingOut,
    ImageOut,
    OverrideOut,
    RetentionOut,
    ScanResultOut,
)
from app.services import retention, storage
from app.services.scanning import DECIDED, WHOLE_LABEL, SubmittedImage, label_of

log = logging.getLogger(__name__)


# --------------------------------------------------------------------------- writing


def find_or_create_product(
    db: Session,
    *,
    name: str,
    brand: str | None,
    category: str | None,
    gtin: str | None,
    is_imported: bool,
    created_by: User,
) -> Product:
    """One product, so re-inspections of the same pack sit on one timeline."""
    statement = select(Product).where(Product.name == name)
    statement = statement.where(Product.brand == brand) if brand else statement
    existing = db.execute(statement).scalars().first()
    if existing is not None:
        return existing

    product = Product(
        name=name,
        brand=brand,
        category=category,
        gtin=gtin,
        is_imported=is_imported,
        created_by_id=created_by.id,
    )
    db.add(product)
    db.flush()
    return product


def save_scan(
    db: Session,
    outcome: ScanOutcome,
    ruleset: RuleSet,
    images: list[SubmittedImage],
    *,
    product: Product,
    created_by: User,
    latitude: float | None = None,
    longitude: float | None = None,
    place_name: str | None = None,
    notes: str | None = None,
) -> Scan:
    """Persist one scan and everything it was decided from."""
    from app.models.enums import ScanStatus

    scale = outcome.scale
    scan = Scan(
        product_id=product.id,
        channel=outcome.context.channel,
        status=ScanStatus.COMPLETE,
        ruleset_version=outcome.ruleset_version,
        extractor_version=outcome.extractor_version,
        scan_date=outcome.context.scan_date,
        mm_per_px=scale.mm_per_px,
        scale_source=str(scale.source),
        scale_confidence=scale.confidence,
        scale_detail=scale.detail,
        pdp_area_cm2=outcome.pdp_area_cm2,
        panel_method=outcome.panel_method,
        exemption_id=outcome.exemption_id,
        pipeline_notes=list(outcome.notes),
        compliance_score=outcome.compliance_score,
        verdict=Verdict(outcome.verdict),
        latitude=latitude,
        longitude=longitude,
        place_name=place_name,
        notes=notes,
        created_by_id=created_by.id,
    )
    db.add(scan)
    db.flush()

    blocks_by_image: dict[str, list] = {}
    for block in outcome.ocr_blocks:
        blocks_by_image.setdefault(block.image_id or "", []).append(
            {
                "text": block.text,
                "polygon": block.polygon,
                "confidence": block.confidence,
            }
        )

    for submitted in images:
        width, height = submitted.size
        db.add(
            ScanImage(
                id=submitted.image_id,
                scan_id=scan.id,
                kind=submitted.kind,
                storage_key=storage.put_image(
                    submitted.image, scan_id=scan.id, image_id=submitted.image_id
                ),
                original_filename=submitted.filename,
                width=width,
                height=height,
                # Kept so a scan can be re-judged against an amended ruleset without
                # asking the officer to photograph the pack again.
                ocr_blocks=blocks_by_image.get(submitted.image_id, []),
            )
        )

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
        db.add(_finding_row(scan.id, result))

    db.flush()
    return scan


def _finding_row(scan_id: str, result: FindingResult) -> Finding:
    return Finding(
        scan_id=scan_id,
        rule_id=result.rule_id,
        title=result.title,
        citation=result.citation,
        status=FindingStatus(result.status),
        severity=Severity(result.severity),
        message=result.message,
        remediation=result.remediation,
        detail=result.detail or {},
        evidence_bbox=result.evidence_bbox,
        evidence_image_id=result.evidence_image_id,
    )


# --------------------------------------------------------------------------- reading


def load_scan(db: Session, scan_id: str) -> Scan | None:
    statement = (
        select(Scan)
        .where(Scan.id == scan_id)
        .options(
            selectinload(Scan.findings),
            selectinload(Scan.fields),
            selectinload(Scan.images),
            selectinload(Scan.product),
        )
    )
    return db.execute(statement).scalars().first()


def _evidence_for(
    finding: Finding,
    rule_fields: dict[str, tuple[str, ...]],
    fields: dict[str, ExtractedField],
) -> EvidenceOut:
    """The same join `scanning` does, over stored rows instead of pipeline objects."""
    candidates = [k for k in rule_fields.get(finding.rule_id, ()) if k]
    if not candidates:
        return EvidenceOut(located=False, note=WHOLE_LABEL)

    value: ExtractedField | None = None
    if finding.evidence_bbox is not None:
        value = next(
            (
                fields[k]
                for k in candidates
                if k in fields
                and fields[k].bbox == finding.evidence_bbox
                and fields[k].source_image_id == finding.evidence_image_id
            ),
            None,
        )
    if value is None:
        value = next(
            (fields[k] for k in candidates if k in fields and (fields[k].raw_text or "").strip()),
            None,
        )

    if value is None or not (value.raw_text or "").strip():
        missing = ", ".join(label_of(k) for k in candidates)
        return EvidenceOut(
            located=False,
            field_key=candidates[0],
            note=f"No {missing} declaration was located on the submitted images.",
        )

    return EvidenceOut(
        located=True,
        field_key=value.field_key,
        raw_text=value.raw_text,
        confidence=round(value.confidence, 4),
        bbox=finding.evidence_bbox or value.bbox,
        image_id=finding.evidence_image_id or value.source_image_id,
    )


def _retention_out(scan: Scan) -> RetentionOut:
    # Feature 6 swaps settings.retention_days for the effective (admin-overridable)
    # value; every describe() caller already threads it through.
    state = retention.describe(scan, settings.retention_days)
    return RetentionOut(
        case_open=state.case_open,
        decided_at=state.decided_at,
        decided_by_id=state.decided_by_id,
        eligible_for_deletion=state.eligible_for_deletion,
        eligible_on=state.eligible_on,
        summary=state.summary,
    )


def to_response(scan: Scan, ruleset: RuleSet) -> ScanResultOut:
    """Rebuild the API shape from stored rows. The only path a client ever sees."""
    rule_fields = {
        r.id: tuple(k for k in (r.field_key, *r.field_keys) if k) for r in ruleset.rules
    }
    fields = {f.field_key: f for f in scan.fields}
    blocks_per_image = {i.id: len(i.ocr_blocks or []) for i in scan.images}

    # Coverage and the standing verdict are recomputed rather than stored: both are
    # pure functions of the findings as they are now, so deriving them cannot disagree
    # with the findings the way a stale column could. `scan.verdict` and
    # `scan.compliance_score` remain the automated result, untouched by overrides.
    as_results = [
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
    decided, applicable = coverage(as_results)
    standing_score = compute_score(as_results)
    standing_verdict = compute_verdict(as_results, standing_score)

    return ScanResultOut(
        scan_id=scan.id,
        product_id=scan.product_id,
        product_name=scan.product.name if scan.product else None,
        channel=scan.channel,
        scan_date=scan.scan_date,
        ruleset_version=scan.ruleset_version or ruleset.version,
        extractor_version=scan.extractor_version or "",
        revision=scan.revision or 1,
        created_at=scan.created_at,
        retention=_retention_out(scan),
        deleted_at=scan.deleted_at,
        deleted_reason=scan.deleted_reason,
        assessment=AssessmentOut(
            verdict=standing_verdict,
            score=standing_score,
            automated_verdict=scan.verdict or Verdict.INCONCLUSIVE,
            automated_score=scan.compliance_score,
            rules_decided=decided,
            rules_applicable=applicable,
            failed=sum(1 for f in scan.findings if f.status is FindingStatus.FAIL),
            needs_review=sum(1 for f in scan.findings if f.status is FindingStatus.NEEDS_REVIEW),
            overridden=sum(1 for f in scan.findings if f.original_status is not None),
            exemption_id=scan.exemption_id,
        ),
        calibration=CalibrationOut(
            calibrated=bool(scan.mm_per_px and scan.mm_per_px > 0),
            source=scan.scale_source or "NONE",
            mm_per_px=scan.mm_per_px,
            confidence=round(scan.scale_confidence or 0.0, 4),
            detail=scan.scale_detail or "",
            pdp_area_cm2=scan.pdp_area_cm2,
            panel_method=scan.panel_method or "not determined",
        ),
        findings=[
            FindingOut(
                rule_id=f.rule_id,
                title=f.title,
                citation=f.citation,
                status=f.status,
                severity=f.severity,
                message=f.message,
                remediation=f.remediation,
                detail=f.detail or {},
                evidence=_evidence_for(f, rule_fields, fields),
                decided=f.status in DECIDED,
                override=(
                    OverrideOut(
                        original_status=f.original_status,
                        reason=f.override_reason,
                        overridden_by_id=f.overridden_by_id,
                        overridden_at=f.overridden_at,
                    )
                    if f.original_status is not None
                    else None
                ),
            )
            for f in sorted(scan.findings, key=lambda f: f.rule_id)
        ],
        fields=[
            FieldOut(
                field_key=f.field_key,
                raw_text=f.raw_text,
                parsed=f.normalized,
                confidence=round(f.confidence, 4),
                bbox=f.bbox,
                image_id=f.source_image_id,
                glyph_height_mm=f.glyph_height_mm,
                glyph_width_mm=f.glyph_width_mm,
            )
            for f in sorted(scan.fields, key=lambda f: f.field_key)
        ],
        images=[
            ImageOut(
                image_id=i.id,
                kind=str(i.kind),
                filename=i.original_filename,
                width=i.width,
                height=i.height,
                blocks_read=blocks_per_image.get(i.id, 0),
            )
            for i in scan.images
        ],
        notes=list(scan.pipeline_notes or []),
    )


def list_scans(
    db: Session,
    *,
    verdict: Verdict | None = None,
    product_id: str | None = None,
    rule_id: str | None = None,
    since: date | None = None,
    limit: int = 50,
    offset: int = 0,
    include_deleted: bool = False,
) -> tuple[list[Scan], int]:
    """Scans newest first, with the total before paging.

    Soft-deleted scans are excluded by default. Their row and deletion event stay in
    the audit trail, but they are not evidence any more and do not belong in a working
    listing.
    """
    statement = select(Scan).options(selectinload(Scan.product), selectinload(Scan.findings))
    if not include_deleted:
        statement = statement.where(Scan.deleted_at.is_(None))
    if verdict is not None:
        statement = statement.where(Scan.verdict == verdict)
    if product_id is not None:
        statement = statement.where(Scan.product_id == product_id)
    if since is not None:
        statement = statement.where(Scan.scan_date >= since)
    if rule_id is not None:
        statement = statement.where(
            Scan.id.in_(
                select(Finding.scan_id).where(
                    Finding.rule_id == rule_id, Finding.status == FindingStatus.FAIL
                )
            )
        )

    rows = db.execute(statement.order_by(Scan.created_at.desc())).scalars().all()
    return list(rows[offset : offset + limit]), len(rows)
