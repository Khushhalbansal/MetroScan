"""Run a scan for the API, and shape the result without weakening it.

This module is deliberately thin. It does not decide anything: `app.pipeline.runner`
judges the package and `app.rules.engine` decides each rule, and neither is reachable
from here except by calling it. What this module does is the join the engine cannot do
for itself — putting each finding back next to the declaration it was decided from, so
the confidence and the pixels travel with the verdict instead of being looked up again
by every client that wants to show them.

Two things are pointedly *not* offered here:

  * No caller-supplied scale. `run_scan` accepts a manual reference, and exposing it
    over HTTP would let any client hand the server a millimetres-per-pixel figure and
    receive measured-looking Rule 8 findings back. Calibration comes from a fiducial the
    camera actually saw, or the geometry rules go to an officer.
  * No filtering. Every rule that was evaluated is returned, including the ones that
    passed and the ones that were not applicable, because "what did you check" is part
    of the finding and a client that only receives failures cannot answer it.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import date

import numpy as np

from app.models.enums import Channel, FindingStatus
from app.pipeline.engine_ocr import OcrEngine
from app.pipeline.runner import ScanInput, ScanOutcome, run_scan
from app.rules.loader import ruleset_for_date
from app.rules.schema import FieldValue, FindingResult, Rule, RuleSet
from app.schemas.scan import (
    AssessmentOut,
    CalibrationOut,
    EvidenceOut,
    FieldOut,
    FindingOut,
    ImageOut,
    RetentionOut,
    ScanResultOut,
)

log = logging.getLogger(__name__)

DECIDED = (FindingStatus.PASS, FindingStatus.FAIL)

# A rule that judges the label as a whole rather than one declaration — legibility,
# grouping, a semantic flag. Absent evidence here is not a missing declaration.
WHOLE_LABEL = "This rule is assessed across the label as a whole, not one declaration."


@dataclass
class SubmittedImage:
    """One decoded photograph, with the identity it keeps through the whole pipeline."""

    image_id: str
    image: np.ndarray
    kind: str = "FRONT"
    filename: str | None = None

    @property
    def size(self) -> tuple[int, int]:
        height, width = self.image.shape[:2]
        return int(width), int(height)


def label_of(key: str) -> str:
    """A field key as an officer would read it. Shared with the persistence layer."""
    return key.replace("_", " ")


def _resolve_evidence(
    finding: FindingResult,
    rule: Rule | None,
    fields: dict[str, FieldValue],
) -> EvidenceOut:
    """Put a finding back beside the declaration it was decided from.

    The engine records the bbox and image it cited but not which declaration that was,
    because a rule reasons about parsed attributes and has no need to name its own
    field afterwards. The ruleset does know, so the join happens here rather than by
    widening the engine's output type.
    """
    named = (rule.field_key, *rule.field_keys) if rule else ()
    candidates = [k for k in named if k]

    if not candidates:
        return EvidenceOut(located=False, note=WHOLE_LABEL)

    # With several candidate fields, the one the engine cited is identifiable by the
    # bbox it copied out. With one, it is unambiguous.
    value: FieldValue | None = None
    if finding.evidence_bbox is not None:
        value = next(
            (
                fields[k]
                for k in candidates
                if k in fields
                and fields[k].bbox == finding.evidence_bbox
                and fields[k].image_id == finding.evidence_image_id
            ),
            None,
        )
    if value is None:
        value = next((fields[k] for k in candidates if k in fields and fields[k].present), None)

    if value is None or not value.present:
        missing = ", ".join(label_of(k) for k in candidates)
        return EvidenceOut(
            located=False,
            field_key=candidates[0],
            note=f"No {missing} declaration was located on the submitted images.",
        )

    return EvidenceOut(
        located=True,
        field_key=value.key,
        raw_text=value.raw_text,
        confidence=round(value.confidence, 4),
        bbox=finding.evidence_bbox or value.bbox,
        image_id=finding.evidence_image_id or value.image_id,
    )


def to_response(
    outcome: ScanOutcome,
    ruleset: RuleSet,
    images: list[SubmittedImage],
    *,
    scan_id: str,
) -> ScanResultOut:
    """Shape a pipeline outcome for the wire. Adds context; removes nothing."""
    rules_by_id = {r.id: r for r in ruleset.rules}
    blocks_per_image: dict[str, int] = {}
    for block in outcome.ocr_blocks:
        key = block.image_id or ""
        blocks_per_image[key] = blocks_per_image.get(key, 0) + 1

    findings = [
        FindingOut(
            rule_id=f.rule_id,
            title=f.title,
            citation=f.citation,
            status=f.status,
            severity=f.severity,
            message=f.message,
            remediation=f.remediation,
            detail=f.detail,
            evidence=_resolve_evidence(f, rules_by_id.get(f.rule_id), outcome.fields),
            decided=f.status in DECIDED,
        )
        for f in outcome.findings
    ]

    decided, applicable = outcome.coverage
    scale = outcome.scale

    return ScanResultOut(
        scan_id=scan_id,
        channel=outcome.context.channel,
        scan_date=outcome.context.scan_date,
        ruleset_version=outcome.ruleset_version,
        extractor_version=outcome.extractor_version,
        revision=1,
        # A preview is not stored, so it has no retention decision. Not eligible for
        # deletion, and not applicable — there is nothing to delete.
        retention=RetentionOut(
            case_open=None,
            eligible_for_deletion=False,
            summary="This is a preview and has not been filed.",
        ),
        assessment=AssessmentOut(
            # Nothing has been overridden on an unsaved scan, so the standing position
            # and the automated one are necessarily the same. They are both reported
            # anyway, so the preview and the filed record have one shape.
            verdict=outcome.verdict,
            score=outcome.compliance_score,
            automated_verdict=outcome.verdict,
            automated_score=outcome.compliance_score,
            rules_decided=decided,
            rules_applicable=applicable,
            failed=sum(1 for f in outcome.findings if f.status is FindingStatus.FAIL),
            needs_review=sum(
                1 for f in outcome.findings if f.status is FindingStatus.NEEDS_REVIEW
            ),
            exemption_id=outcome.exemption_id,
        ),
        calibration=CalibrationOut(
            calibrated=scale.usable,
            source=str(scale.source),
            mm_per_px=scale.mm_per_px,
            confidence=round(scale.confidence, 4),
            detail=scale.detail,
            pdp_area_cm2=outcome.pdp_area_cm2,
            panel_method=outcome.panel_method,
        ),
        findings=findings,
        fields=[
            FieldOut(
                field_key=v.key,
                raw_text=v.raw_text,
                parsed=v.parsed.as_dict() if v.parsed is not None else None,
                confidence=round(v.confidence, 4),
                bbox=v.bbox,
                image_id=v.image_id,
                glyph_height_mm=v.glyph_height_mm,
                glyph_width_mm=v.glyph_width_mm,
            )
            for v in outcome.fields.values()
        ],
        images=[
            ImageOut(
                image_id=i.image_id,
                kind=i.kind,
                filename=i.filename,
                width=i.size[0],
                height=i.size[1],
                blocks_read=blocks_per_image.get(i.image_id, 0),
            )
            for i in images
        ],
        notes=outcome.notes,
    )


def run(
    images: list[SubmittedImage],
    *,
    channel: Channel = Channel.PHYSICAL,
    is_imported: bool = False,
    category: str | None = None,
    is_raised: bool = False,
    scan_date: date | None = None,
    coin: str | None = None,
    ocr_engine: OcrEngine | None = None,
) -> tuple[ScanOutcome, RuleSet]:
    """Judge one submission, returning the raw outcome and the ruleset that judged it.

    Blocking and CPU-bound — call it off the event loop. The ruleset comes back with
    the outcome because everything downstream (persistence, reports) needs the rules to
    interpret the findings, and re-resolving it by date risks a different answer if the
    rules directory changed in between.
    """
    scan_date = scan_date or date.today()
    ruleset = ruleset_for_date(scan_date)

    outcome = run_scan(
        [ScanInput(image=i.image, image_id=i.image_id, kind=i.kind) for i in images],
        channel=channel,
        is_imported=is_imported,
        category=category,
        is_raised=is_raised,
        scan_date=scan_date,
        ruleset=ruleset,
        ocr_engine=ocr_engine,
        coin=coin,
    )
    return outcome, ruleset


def analyse(images: list[SubmittedImage], **kwargs) -> ScanResultOut:
    """Judge one submission without storing it — the preview path."""
    outcome, ruleset = run(images, **kwargs)
    return to_response(outcome, ruleset, images, scan_id=uuid.uuid4().hex)


def new_image_id() -> str:
    return uuid.uuid4().hex
