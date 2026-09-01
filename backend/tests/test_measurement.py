"""The measurement chain, validated against images rendered at known physical sizes.

These are the tests that decide whether a Rule 8 finding means anything. Each one
renders text at a known millimetre height, photographs it (in effect), recovers the
scale from a fiducial, and checks that the measurement comes back.
"""

from __future__ import annotations

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2", reason="OpenCV is required for the measurement tests")

# ruff: noqa: E402 - these modules import cv2, so the skip above must run first.
from app.pipeline.geometry import measure_ink, measure_span, principal_display_panel_area
from app.pipeline.ocr import OcrBlock, Span
from app.pipeline.scale import (
    ARUCO_MARKER_MM,
    ScaleSource,
    detect_aruco,
    detect_id_card,
    estimate,
    from_manual_reference,
)

# Every synthetic page is rendered at this resolution, so 1 px is exactly 0.05 mm.
PX_PER_MM = 20.0
MM_PER_PX = 1.0 / PX_PER_MM


def blank(width_mm: float = 120, height_mm: float = 90) -> np.ndarray:
    w, h = int(width_mm * PX_PER_MM), int(height_mm * PX_PER_MM)
    return np.full((h, w, 3), 245, np.uint8)


def put_aruco(page: np.ndarray, at_mm: tuple[float, float] = (5, 5)) -> np.ndarray:
    """Stamp a scale-card marker of the real ARUCO_MARKER_MM size onto the page."""
    side_px = int(ARUCO_MARKER_MM * PX_PER_MM)
    d = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
    marker = cv2.cvtColor(cv2.aruco.generateImageMarker(d, 7, side_px), cv2.COLOR_GRAY2BGR)
    x, y = int(at_mm[0] * PX_PER_MM), int(at_mm[1] * PX_PER_MM)
    page[y : y + side_px, x : x + side_px] = marker
    return page


def put_text(
    page: np.ndarray,
    text: str,
    cap_height_mm: float,
    at_mm: tuple[float, float],
) -> list[float]:
    """Draw text whose capital letters are exactly cap_height_mm of *ink* tall.

    A stroke of thickness t is centred on the glyph path, so the ink extends t/2 beyond
    it on each side and the printed letter stands (path + t) tall. Printed type really
    does behave this way, so the scale is solved against the path height and the
    thickness added back — otherwise the fixture asks the measurement to be wrong.
    """
    target_px = cap_height_mm * PX_PER_MM
    font = cv2.FONT_HERSHEY_SIMPLEX
    thickness = max(1, int(round(target_px / 10)))
    # Hershey scale 1.0 gives a cap height of ~21 px; solve for the scale we need.
    (_, cap_at_1), _ = cv2.getTextSize("H", font, 1.0, 1)
    scale = max(target_px - thickness, 1.0) / cap_at_1
    (w, h), baseline = cv2.getTextSize(text, font, scale, thickness)
    x, y = int(at_mm[0] * PX_PER_MM), int(at_mm[1] * PX_PER_MM)
    cv2.putText(page, text, (x, y + h), font, scale, (20, 20, 20), thickness, cv2.LINE_AA)
    return [float(x), float(y), float(w), float(h + baseline)]


def span_for(bbox: list[float], text: str) -> Span:
    x, y, w, h = bbox
    block = OcrBlock(
        text=text,
        polygon=[[x, y], [x + w, y], [x + w, y + h], [x, y + h]],
        confidence=0.95,
        image_id="img1",
    )
    return Span(0, len(text), [block])


# ------------------------------------------------------------------ scale recovery


def test_aruco_recovers_the_true_scale():
    page = put_aruco(blank())
    result = detect_aruco(page)
    assert result is not None and result.source is ScaleSource.ARUCO
    assert result.mm_per_px == pytest.approx(MM_PER_PX, rel=0.03)
    assert result.confidence > 0.8


def test_estimate_prefers_the_scale_card():
    result = estimate(put_aruco(blank()))
    assert result.source is ScaleSource.ARUCO
    assert result.usable


def test_a_page_with_no_fiducial_reports_no_scale():
    result = estimate(blank())
    assert not result.usable
    assert result.source is ScaleSource.NONE
    assert result.confidence == 0.0


def test_id_card_recovers_the_true_scale():
    page = blank(160, 120)
    w = int(85.60 * PX_PER_MM)
    h = int(53.98 * PX_PER_MM)
    cv2.rectangle(page, (200, 200), (200 + w, 200 + h), (60, 90, 140), -1)
    cv2.rectangle(page, (200, 200), (200 + w, 200 + h), (20, 20, 20), 3)
    result = detect_id_card(page)
    assert result is not None
    assert result.mm_per_px == pytest.approx(MM_PER_PX, rel=0.05)


def test_manual_reference_is_exact():
    result = from_manual_reference(reference_mm=50.0, measured_px=1000.0)
    assert result.mm_per_px == 0.05
    assert result.source is ScaleSource.MANUAL


def test_an_unusable_manual_reference_is_rejected():
    assert not from_manual_reference(0, 100).usable
    assert not from_manual_reference(50, 0).usable


def test_scale_converts_pixels_and_areas():
    result = from_manual_reference(reference_mm=50.0, measured_px=1000.0)  # 0.05 mm/px
    assert result.px_to_mm(40) == pytest.approx(2.0)
    # 400x400 px = 20x20 mm = 4 cm2
    assert result.area_px_to_cm2(400 * 400) == pytest.approx(4.0)


# --------------------------------------------------------------- glyph measurement


@pytest.mark.parametrize("cap_mm", [1.0, 1.5, 2.0, 3.0, 4.0, 6.0])
def test_ink_measurement_recovers_rendered_type_size(cap_mm):
    page = blank()
    bbox = put_text(page, "200 g NET", cap_mm, at_mm=(10, 30))
    measured = measure_ink(page, bbox)
    assert measured is not None
    height_px, _ = measured
    assert height_px * MM_PER_PX == pytest.approx(cap_mm, rel=0.18), (
        f"rendered {cap_mm} mm, measured {height_px * MM_PER_PX:.2f} mm"
    )


def test_measure_span_reports_millimetres_via_the_scale_card():
    page = put_aruco(blank())
    bbox = put_text(page, "Net Qty 200 g", 2.0, at_mm=(10, 55))
    scale = estimate(page)
    metrics = measure_span(span_for(bbox, "Net Qty 200 g"), scale, page)
    assert metrics.method == "ink"
    assert metrics.height_mm == pytest.approx(2.0, rel=0.2)
    assert metrics.width_mm and metrics.width_mm > 0


def test_undersized_print_measures_as_undersized():
    """The case the whole product exists to catch."""
    page = put_aruco(blank())
    bbox = put_text(page, "Net Qty 200 g", 1.2, at_mm=(10, 55))
    metrics = measure_span(span_for(bbox, "Net Qty 200 g"), estimate(page), page)
    assert metrics.height_mm is not None and metrics.height_mm < 2.0


def test_compliant_print_measures_as_compliant():
    page = put_aruco(blank())
    bbox = put_text(page, "Net Qty 200 g", 2.6, at_mm=(10, 55))
    metrics = measure_span(span_for(bbox, "Net Qty 200 g"), estimate(page), page)
    assert metrics.height_mm is not None and metrics.height_mm >= 2.0


def test_ink_measurement_beats_the_box_estimate():
    """The OCR box overstates type size; that is why measure_ink exists."""
    page = put_aruco(blank())
    bbox = put_text(page, "Net Qty 200 g", 2.0, at_mm=(10, 55))
    scale = estimate(page)
    span = span_for(bbox, "Net Qty 200 g")

    from_ink = measure_span(span, scale, page)
    from_box = measure_span(span, scale, None)

    assert from_ink.method == "ink" and from_box.method == "box"
    assert abs(from_ink.height_mm - 2.0) < abs(from_box.height_mm - 2.0)
    assert from_ink.confidence > from_box.confidence


def test_light_on_dark_print_is_measured_too():
    page = np.full((900, 1600, 3), 30, np.uint8)
    target_px = 2.5 * PX_PER_MM
    (_, cap_at_1), _ = cv2.getTextSize("H", cv2.FONT_HERSHEY_SIMPLEX, 1.0, 1)
    scale_f = target_px / cap_at_1
    (w, h), b = cv2.getTextSize("MRP 45.00", cv2.FONT_HERSHEY_SIMPLEX, scale_f, 2)
    cv2.putText(page, "MRP 45.00", (200, 600 + h), cv2.FONT_HERSHEY_SIMPLEX, scale_f,
                (240, 240, 240), 2, cv2.LINE_AA)
    measured = measure_ink(page, [200.0, 600.0, float(w), float(h + b)])
    assert measured is not None
    assert measured[0] * MM_PER_PX == pytest.approx(2.5, rel=0.25)


def test_nothing_is_measured_without_a_scale():
    page = blank()
    bbox = put_text(page, "Net Qty 200 g", 2.0, at_mm=(10, 30))
    metrics = measure_span(span_for(bbox, "Net Qty 200 g"), estimate(page), page)
    assert metrics.height_mm is None and metrics.confidence == 0.0


def test_an_empty_crop_measures_nothing():
    assert measure_ink(blank(), [0.0, 0.0, 1.0, 1.0]) is None


# ----------------------------------------------------------- display panel area


def test_panel_area_is_reported_in_square_centimetres():
    page = put_aruco(blank(120, 90))
    area_cm2, method = principal_display_panel_area(page, estimate(page))
    assert area_cm2 is not None
    # 120 x 90 mm = 108 cm2; the estimate should land in the right order of magnitude.
    assert 40 < area_cm2 < 160, f"got {area_cm2} cm2 via {method}"


def test_panel_area_is_not_the_scale_card():
    """The 40 mm marker is a crisp quadrilateral; it must never be read as the panel."""
    page = put_aruco(blank(120, 90))
    scale = estimate(page)
    assert scale.fiducial_bbox is not None
    area_cm2, _ = principal_display_panel_area(page, scale)
    marker_area_cm2 = (ARUCO_MARKER_MM / 10) ** 2  # 16 cm2
    assert area_cm2 is not None
    assert abs(area_cm2 - marker_area_cm2) > 1.0, "panel area collapsed onto the fiducial"


@pytest.mark.parametrize(
    "shape",
    [(3, 3, 3), (1, 1, 3), (12, 8, 3)],
)
def test_an_implausibly_small_panel_is_rejected_rather_than_believed(shape):
    """A collapsed area picks the smallest, most lenient Rule 8 band, so undersized
    print would clear a 1 mm requirement instead of the real one."""
    tiny = np.full(shape, 245, np.uint8)
    area_cm2, method = principal_display_panel_area(tiny, from_manual_reference(50.0, 1000.0))
    assert area_cm2 is None, f"believed a {area_cm2} cm² panel"
    assert "not a plausible panel" in method


def test_a_rejected_panel_leaves_rule_eight_for_review(ruleset):
    """The consequence of the above, through the engine."""
    from app.pipeline.declarations import QuantityDeclaration
    from app.rules.engine import evaluate
    from app.rules.schema import FieldValue, ScanContext
    from app.rules.units import Basis

    ctx = ScanContext(
        fields={
            "net_quantity": FieldValue(
                key="net_quantity", raw_text="Net Qty 200 g",
                parsed=QuantityDeclaration(value=200, unit="g", basis=Basis.WEIGHT),
                confidence=0.95,
                bbox=[1, 1, 10, 10], image_id="img1",
                glyph_height_mm=0.4, glyph_width_mm=0.2,
            )
        },
        blocks_read=12,
        mm_per_px=0.05,
        pdp_area_cm2=0.0,  # what a collapsed detection used to hand over
    )
    findings, _ = evaluate(ctx, ruleset)
    height = next(f for f in findings if f.rule_id == "FONT_HEIGHT_NET_QUANTITY")
    assert height.status.value == "NEEDS_REVIEW"
    assert height.detail["reason"] == "no_pdp_area"


def test_a_real_panel_is_still_accepted():
    page = put_aruco(blank(120, 90))
    area_cm2, method = principal_display_panel_area(page, estimate(page))
    assert area_cm2 is not None and area_cm2 > 1.0
    assert "rejected" not in method


def test_panel_area_needs_a_scale():
    page = blank()
    area_cm2, method = principal_display_panel_area(page, estimate(page))
    assert area_cm2 is None
    assert "no scale" in method
