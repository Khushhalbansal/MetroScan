"""Measure printed characters in millimetres.

An OCR box is drawn around a whole line, so its height includes ascenders, descenders
and whatever padding the detector added. Rule 8 asks about the height of the letters
and numerals themselves. Measuring the box would systematically overstate the type
size and let undersized print pass, so this module goes back to the pixels and
measures the ink.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np

from app.pipeline.ocr import Span
from app.pipeline.scale import ScaleEstimate

log = logging.getLogger(__name__)

try:
    import cv2

    HAVE_CV2 = True
except ImportError:  # pragma: no cover
    cv2 = None  # type: ignore[assignment]
    HAVE_CV2 = False

# An OCR line box is this much taller than the glyphs inside it, typically. Used only
# when the pixels cannot be measured directly.
BOX_TO_GLYPH_RATIO = 0.62

# Smallest principal display panel we will believe, in cm². A 10 mm x 10 mm face is
# already below anything sold at retail, so a smaller figure means the detection failed.
MIN_PLAUSIBLE_PANEL_CM2 = 1.0


@dataclass
class GlyphMetrics:
    """Measured type size for one declaration."""

    height_mm: float | None
    width_mm: float | None
    height_px: float | None
    method: str  # "ink" (measured from pixels) or "box" (inferred from the OCR box)
    confidence: float

    @property
    def aspect(self) -> float | None:
        if self.height_mm and self.width_mm:
            return self.width_mm / self.height_mm
        return None


UNMEASURED = GlyphMetrics(None, None, None, "none", 0.0)


def _crop(image: np.ndarray, bbox: list[float], pad: int = 2) -> np.ndarray | None:
    x, y, w, h = (int(round(v)) for v in bbox)
    y0, y1 = max(0, y - pad), min(image.shape[0], y + h + pad)
    x0, x1 = max(0, x - pad), min(image.shape[1], x + w + pad)
    if y1 - y0 < 3 or x1 - x0 < 3:
        return None
    return image[y0:y1, x0:x1]


def measure_ink(image: np.ndarray, bbox: list[float]) -> tuple[float, float] | None:
    """Height and mean advance width of the actual glyphs, in pixels.

    Binarises the crop, then takes the height of the x-height band rather than the
    full ink extent, so a single tall capital or a descender does not stand in for
    the type size.
    """
    if not HAVE_CV2:
        return None
    crop = _crop(image, bbox)
    if crop is None:
        return None

    grey = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.ndim == 3 else crop
    # Otsu on both polarities — packs print dark-on-light and light-on-dark equally.
    _, dark = cv2.threshold(grey, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    _, light = cv2.threshold(grey, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    binary = dark if dark.mean() < light.mean() else light

    count, _, stats, _ = cv2.connectedComponentsWithStats(binary, connectivity=8)
    if count <= 1:
        return None

    # Drop noise and anything spanning the whole crop (rules, borders, the box edge).
    h_crop, w_crop = binary.shape[:2]
    glyphs = [
        (s[cv2.CC_STAT_HEIGHT], s[cv2.CC_STAT_WIDTH])
        for s in stats[1:]
        if s[cv2.CC_STAT_AREA] >= 4
        and s[cv2.CC_STAT_HEIGHT] >= 3
        and s[cv2.CC_STAT_HEIGHT] <= h_crop * 0.95
        and s[cv2.CC_STAT_WIDTH] <= w_crop * 0.9
    ]
    if len(glyphs) < 2:
        return None

    heights = np.array([g[0] for g in glyphs], dtype=float)
    widths = np.array([g[1] for g in glyphs], dtype=float)

    # Rule 8 measures the height of a letter or numeral, which in practice means cap
    # and digit height. Capitals and digits are the most common component height in a
    # declaration like "200 g" or "MRP 45.00", so the median lands on exactly that,
    # while a mean or an upper percentile gets dragged up by descenders (g, y, Q).
    height_px = float(np.median(heights))
    # Width per character, ignoring the widest few (joined letters, merged strokes).
    width_px = float(np.median(widths[widths <= np.percentile(widths, 90)]))
    if height_px <= 0 or width_px <= 0:
        return None
    return height_px, width_px


def measure_span(
    span: Span,
    scale: ScaleEstimate,
    image: np.ndarray | None = None,
) -> GlyphMetrics:
    """Millimetre type size for one extracted declaration."""
    if not scale.usable or span.bbox is None:
        return UNMEASURED

    if image is not None and (measured := measure_ink(image, span.bbox)) is not None:
        height_px, width_px = measured
        return GlyphMetrics(
            height_mm=round(scale.px_to_mm(height_px) or 0.0, 2),
            width_mm=round(scale.px_to_mm(width_px) or 0.0, 2),
            height_px=round(height_px, 1),
            method="ink",
            confidence=round(scale.confidence * 0.95, 2),
        )

    # Fall back to the OCR box, discounted for the padding it carries. Lower
    # confidence, because this is an inference rather than a measurement.
    box_height = span.height_px
    if not box_height:
        return UNMEASURED
    height_px = box_height * BOX_TO_GLYPH_RATIO
    char_width = span.char_width_px
    return GlyphMetrics(
        height_mm=round(scale.px_to_mm(height_px) or 0.0, 2),
        width_mm=round(scale.px_to_mm(char_width) or 0.0, 2) if char_width else None,
        height_px=round(height_px, 1),
        method="box",
        confidence=round(scale.confidence * 0.6, 2),
    )


# --------------------------------------------------------------- display panel


def _overlaps(contour: np.ndarray, region: list[float] | None, threshold: float = 0.5) -> bool:
    """True when most of `contour` falls inside `region`."""
    if not region:
        return False
    rx, ry, rw, rh = region
    pts = contour.reshape(-1, 2).astype(float)
    x0, y0 = pts.min(axis=0)
    x1, y1 = pts.max(axis=0)
    inter_w = max(0.0, min(x1, rx + rw) - max(x0, rx))
    inter_h = max(0.0, min(y1, ry + rh) - max(y0, ry))
    own_area = max((x1 - x0) * (y1 - y0), 1.0)
    return (inter_w * inter_h) / own_area >= threshold


def principal_display_panel_area(
    image: np.ndarray,
    scale: ScaleEstimate,
) -> tuple[float | None, str]:
    """Area of the principal display panel in cm², which sets the Rule 8 band.

    Finds the package face by taking the largest well-formed quadrilateral that is
    not the scale fiducial, and falls back to the frame itself when the pack fills it.
    """
    if not HAVE_CV2 or not scale.usable or image is None or image.size == 0:
        return None, "no scale reference"

    frame_area = float(image.shape[0] * image.shape[1])
    grey = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    grey = cv2.bilateralFilter(grey, 7, 60, 60)
    edges = cv2.Canny(grey, 30, 120)
    edges = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    best_area_px = 0.0
    for contour in contours:
        area = cv2.contourArea(contour)
        # The pack should dominate the frame without being the frame border itself.
        if area < frame_area * 0.10 or area > frame_area * 0.97:
            continue
        approx = cv2.approxPolyDP(contour, 0.02 * cv2.arcLength(contour, True), True)
        if len(approx) < 4 or len(approx) > 6:
            continue
        # The scale card is a crisp quadrilateral of exactly the kind this loop is
        # looking for. Measuring it would report the fiducial's area as the package's.
        if _overlaps(contour, scale.fiducial_bbox):
            continue
        best_area_px = max(best_area_px, area)

    method = "detected panel"
    if best_area_px <= 0:
        # The pack fills the frame. Assume the visible face is the display panel.
        best_area_px = frame_area * 0.85
        method = "frame estimate"

    area_cm2 = scale.area_px_to_cm2(best_area_px)
    if area_cm2 is None:
        return None, method

    # The panel area picks the Rule 8 height band, and the smallest band is the most
    # lenient one. A detection that collapses to a sliver would therefore let
    # undersized print through under a 1 mm requirement. No retail display panel is
    # this small, so treat it as a failed detection and let an officer measure.
    if area_cm2 < MIN_PLAUSIBLE_PANEL_CM2:
        return None, f"{method} rejected: {area_cm2:.2f} cm² is not a plausible panel"

    return round(area_cm2, 1), method
