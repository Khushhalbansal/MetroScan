"""Run one scan: photographs in, findings out.

    preprocess -> OCR -> scale -> extract -> measure -> evaluate

Every stage records what it did and how sure it was, because a finding an officer
cannot audit is worth nothing.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import numpy as np

from app.models.enums import Channel
from app.pipeline import fields as field_extractors
from app.pipeline.engine_ocr import OcrEngine, get_engine
from app.pipeline.geometry import measure_span, principal_display_panel_area
from app.pipeline.ocr import OcrBlock, OcrDocument
from app.pipeline.scale import UNKNOWN, ScaleEstimate, estimate, from_manual_reference
from app.rules.engine import coverage, evaluate, score, verdict
from app.rules.loader import ruleset_for_date
from app.rules.schema import FieldValue, FindingResult, RuleSet, ScanContext

log = logging.getLogger(__name__)

try:
    import cv2

    HAVE_CV2 = True
except ImportError:  # pragma: no cover
    cv2 = None  # type: ignore[assignment]
    HAVE_CV2 = False


@dataclass
class ScanInput:
    """One image submitted for a scan."""

    image: np.ndarray
    image_id: str
    kind: str = "FRONT"


@dataclass
class ScanOutcome:
    findings: list[FindingResult]
    fields: dict[str, FieldValue]
    context: ScanContext
    # None when nothing could be decided — never render this as a zero.
    compliance_score: float | None
    # (rules decided, rules applicable). Always show this beside the score: 100% over
    # two decided rules is not the same claim as 100% over twenty.
    coverage: tuple[int, int]
    verdict: Any
    ruleset_version: str
    extractor_version: str
    scale: ScaleEstimate
    pdp_area_cm2: float | None
    panel_method: str
    ocr_blocks: list[OcrBlock] = field(default_factory=list)
    exemption_id: str | None = None
    notes: list[str] = field(default_factory=list)


def preprocess(image: np.ndarray) -> np.ndarray:
    """Modest correction only. Aggressive filtering destroys the thin strokes that
    the Rule 8 measurement depends on, so this deliberately does very little."""
    if not HAVE_CV2 or image is None or image.size == 0:
        return image
    # Downscale only very large phone captures, and never below the detail OCR needs.
    max_edge = 2400
    h, w = image.shape[:2]
    if max(h, w) > max_edge:
        factor = max_edge / max(h, w)
        image = cv2.resize(image, (int(w * factor), int(h * factor)), interpolation=cv2.INTER_AREA)
    return image


def run_scan(
    inputs: list[ScanInput],
    *,
    channel: Channel = Channel.PHYSICAL,
    is_imported: bool = False,
    category: str | None = None,
    is_raised: bool = False,
    scan_date: date | None = None,
    ruleset: RuleSet | None = None,
    ocr_engine: OcrEngine | None = None,
    manual_scale: tuple[float, float] | None = None,
    coin: str | None = None,
    semantic_flags: dict[str, bool] | None = None,
) -> ScanOutcome:
    """Judge one product from its photographs."""
    scan_date = scan_date or date.today()
    ruleset = ruleset or ruleset_for_date(scan_date)
    engine = ocr_engine or get_engine()
    notes: list[str] = []

    images = {i.image_id: preprocess(i.image) for i in inputs}

    # -- OCR every image -----------------------------------------------------
    blocks: list[OcrBlock] = []
    for image_id, image in images.items():
        try:
            blocks.extend(engine.read(image, image_id))
        except Exception as exc:
            log.exception("OCR failed on %s", image_id)
            notes.append(f"Could not read image {image_id}: {exc}")
    doc = OcrDocument.build(blocks)
    if not blocks:
        notes.append("No text was read from the submitted images.")

    # -- Scale, from the image that carries the fiducial ----------------------
    scale = UNKNOWN
    scale_image_id: str | None = None
    if manual_scale:
        scale = from_manual_reference(*manual_scale)
        scale_image_id = next(iter(images), None)
    else:
        for image_id, image in images.items():
            candidate = estimate(image, coin=coin)
            if candidate.usable and candidate.confidence > scale.confidence:
                scale, scale_image_id = candidate, image_id
    if not scale.usable:
        notes.append(
            "No scale reference was found, so character heights could not be measured. "
            "Rule 8 findings are left for review."
        )

    # -- Principal display panel area ----------------------------------------
    pdp_area_cm2, panel_method = None, "not determined"
    if scale.usable and scale_image_id:
        pdp_area_cm2, panel_method = principal_display_panel_area(images[scale_image_id], scale)

    # -- Extract the declarations --------------------------------------------
    extractions = field_extractors.extract_all(doc)

    # -- Measure each one -----------------------------------------------------
    values: dict[str, FieldValue] = {}
    for key, extraction in extractions.items():
        metrics = measure_span(
            extraction.span, scale, images.get(extraction.image_id or "")
        )
        values[key] = FieldValue(
            key=key,
            raw_text=extraction.raw_text,
            parsed=extraction.parsed,
            confidence=extraction.confidence,
            bbox=extraction.bbox,
            image_id=extraction.image_id,
            glyph_height_mm=metrics.height_mm,
            glyph_width_mm=metrics.width_mm,
        )

    # -- Judge ----------------------------------------------------------------
    context = ScanContext(
        channel=channel,
        scan_date=scan_date,
        is_imported=is_imported,
        category=category,
        fields=values,
        mm_per_px=scale.mm_per_px,
        pdp_area_cm2=pdp_area_cm2,
        is_raised=is_raised,
        semantic_flags=semantic_flags or {},
        min_field_confidence=min((v.confidence for v in values.values()), default=0.0),
        blocks_read=len(blocks),
        ocr_confidence=doc.mean_confidence,
    )
    findings, exemption = evaluate(context, ruleset)
    value = score(findings)

    return ScanOutcome(
        findings=findings,
        fields=values,
        context=context,
        compliance_score=value,
        coverage=coverage(findings),
        verdict=verdict(findings, value),
        ruleset_version=ruleset.version,
        extractor_version=f"regex+{engine.name}",
        scale=scale,
        pdp_area_cm2=pdp_area_cm2,
        panel_method=panel_method,
        ocr_blocks=blocks,
        exemption_id=exemption.id if exemption else None,
        notes=notes,
    )
