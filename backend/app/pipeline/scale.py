"""Recover millimetres-per-pixel from a photograph.

Rule 8 is a physical measurement, so nothing about font size can be judged from a
photograph alone — a pixel means nothing without a known length in frame. This module
looks for a fiducial of known size and reports how confident it is. When it finds
nothing it says so, and the engine downgrades every geometry rule to NEEDS_REVIEW
rather than inventing a measurement.

Fiducials, in order of preference:
  1. An ArUco marker from the printable scale card in docs/scale-card.md (40 mm).
  2. A standard ID-1 card (85.60 x 53.98 mm) — an Aadhaar, PAN or debit card.
  3. An Indian ₹5 or ₹10 coin (23.0 / 27.0 mm diameter).
  4. An operator-entered reference length.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import StrEnum

import numpy as np

log = logging.getLogger(__name__)

try:  # imaging is optional so the rule engine and API import cleanly without it
    import cv2

    HAVE_CV2 = True
except ImportError:  # pragma: no cover
    cv2 = None  # type: ignore[assignment]
    HAVE_CV2 = False


# Physical dimensions of the fiducials we accept, in millimetres.
ARUCO_MARKER_MM = 40.0
ID1_CARD_MM = (85.60, 53.98)
COIN_MM = {"INR_5": 23.0, "INR_10": 27.0}


class ScaleSource(StrEnum):
    ARUCO = "ARUCO"
    ID_CARD = "ID_CARD"
    COIN = "COIN"
    MANUAL = "MANUAL"
    NONE = "NONE"


@dataclass
class ScaleEstimate:
    """How many millimetres one pixel spans, and how much to trust that."""

    mm_per_px: float | None
    source: ScaleSource
    confidence: float
    detail: str = ""
    # Where the fiducial sits, [x, y, w, h]. Downstream steps must exclude this region:
    # the scale card is not part of the package, and a panel detector will happily
    # mistake a crisp 40 mm square for the principal display panel.
    fiducial_bbox: list[float] | None = None

    @property
    def usable(self) -> bool:
        return self.mm_per_px is not None and self.mm_per_px > 0

    def px_to_mm(self, px: float) -> float | None:
        # Tested against mm_per_px directly rather than via `usable`, so the None case
        # is narrowed for the type checker as well as guarded at runtime.
        if self.mm_per_px is None or self.mm_per_px <= 0:
            return None
        return px * self.mm_per_px

    def area_px_to_cm2(self, area_px: float) -> float | None:
        if self.mm_per_px is None or self.mm_per_px <= 0:
            return None
        return area_px * (self.mm_per_px**2) / 100.0


UNKNOWN = ScaleEstimate(
    mm_per_px=None,
    source=ScaleSource.NONE,
    confidence=0.0,
    detail="No scale reference found in frame.",
)


def _quad_side_lengths(corners: np.ndarray) -> list[float]:
    pts = corners.reshape(-1, 2).astype(float)
    return [float(np.linalg.norm(pts[i] - pts[(i + 1) % len(pts)])) for i in range(len(pts))]


def _bounds(points: np.ndarray) -> list[float]:
    pts = points.reshape(-1, 2).astype(float)
    x0, y0 = pts.min(axis=0)
    x1, y1 = pts.max(axis=0)
    return [float(x0), float(y0), float(x1 - x0), float(y1 - y0)]


def detect_aruco(image: np.ndarray) -> ScaleEstimate | None:
    """The scale card. Most reliable, because the marker size is known exactly."""
    if not HAVE_CV2:
        return None
    try:
        aruco = cv2.aruco
        dictionary = aruco.getPredefinedDictionary(aruco.DICT_4X4_50)
        detector = aruco.ArucoDetector(dictionary, aruco.DetectorParameters())
        corners, ids, _ = detector.detectMarkers(image)
    except Exception as exc:  # pragma: no cover - depends on the opencv build
        log.debug("aruco detection unavailable: %s", exc)
        return None

    if ids is None or len(corners) == 0:
        return None

    # Average the side length over every marker found; more markers, more confidence.
    sides = [s for c in corners for s in _quad_side_lengths(c)]
    if not sides:
        return None
    mean_side = float(np.mean(sides))
    if mean_side <= 1:
        return None

    spread = float(np.std(sides)) / mean_side
    # A square marker photographed square-on has near-equal sides. Wide spread means
    # the pack was shot at an angle, which makes the estimate less trustworthy.
    confidence = max(0.55, min(0.99, 0.99 - spread * 2.0))
    return ScaleEstimate(
        mm_per_px=ARUCO_MARKER_MM / mean_side,
        source=ScaleSource.ARUCO,
        confidence=round(confidence, 2),
        detail=f"{len(corners)} scale-card marker(s), mean side {mean_side:.0f} px.",
        fiducial_bbox=_bounds(np.concatenate([c.reshape(-1, 2) for c in corners])),
    )


def detect_id_card(image: np.ndarray) -> ScaleEstimate | None:
    """An ID-1 card laid on the pack. Matched on the 1.586 aspect ratio."""
    if not HAVE_CV2:
        return None
    target_ratio = ID1_CARD_MM[0] / ID1_CARD_MM[1]

    grey = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    grey = cv2.bilateralFilter(grey, 9, 75, 75)
    edges = cv2.Canny(grey, 40, 140)
    edges = cv2.dilate(edges, np.ones((3, 3), np.uint8), iterations=1)
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    frame_area = image.shape[0] * image.shape[1]
    best: tuple[float, float, np.ndarray] | None = None  # (ratio error, long side, contour)

    for contour in contours:
        area = cv2.contourArea(contour)
        # A card held against a pack occupies a meaningful but not dominant slice.
        if area < frame_area * 0.01 or area > frame_area * 0.6:
            continue
        approx = cv2.approxPolyDP(contour, 0.02 * cv2.arcLength(contour, True), True)
        if len(approx) != 4 or not cv2.isContourConvex(approx):
            continue
        (_, _), (w, h), _ = cv2.minAreaRect(contour)
        if min(w, h) < 20:
            continue
        long_side, short_side = max(w, h), min(w, h)
        error = abs((long_side / short_side) - target_ratio) / target_ratio
        if error < 0.08 and (best is None or error < best[0]):
            best = (error, long_side, contour)

    if best is None:
        return None
    error, long_side, contour = best
    return ScaleEstimate(
        mm_per_px=ID1_CARD_MM[0] / long_side,
        source=ScaleSource.ID_CARD,
        confidence=round(max(0.5, 0.85 - error * 3), 2),
        detail=f"ID-1 card, long edge {long_side:.0f} px (aspect error {error:.1%}).",
        fiducial_bbox=_bounds(contour),
    )


def detect_coin(image: np.ndarray, denomination: str = "INR_10") -> ScaleEstimate | None:
    """A coin beside the pack. Least precise — two denominations are close in size."""
    if not HAVE_CV2:
        return None
    diameter_mm = COIN_MM.get(denomination)
    if diameter_mm is None:
        return None

    grey = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    grey = cv2.medianBlur(grey, 5)
    min_dim = min(image.shape[:2])
    circles = cv2.HoughCircles(
        grey,
        cv2.HOUGH_GRADIENT,
        dp=1.2,
        minDist=min_dim // 4,
        param1=120,
        param2=45,
        minRadius=int(min_dim * 0.02),
        maxRadius=int(min_dim * 0.18),
    )
    if circles is None:
        return None

    radii = np.asarray(circles, dtype=float)[0, :, 2]
    radius = float(np.median(radii))
    if radius <= 1:
        return None
    return ScaleEstimate(
        mm_per_px=diameter_mm / (radius * 2),
        source=ScaleSource.COIN,
        confidence=0.6 if len(radii) == 1 else 0.45,
        detail=f"₹{denomination.split('_')[1]} coin, radius {radius:.0f} px.",
    )


def from_manual_reference(reference_mm: float, measured_px: float) -> ScaleEstimate:
    """An officer measured something in frame and typed its real length."""
    if reference_mm <= 0 or measured_px <= 0:
        return UNKNOWN
    return ScaleEstimate(
        mm_per_px=reference_mm / measured_px,
        source=ScaleSource.MANUAL,
        confidence=0.9,
        detail=f"Operator reference: {reference_mm:g} mm over {measured_px:.0f} px.",
    )


def estimate(image: np.ndarray, *, coin: str | None = None) -> ScaleEstimate:
    """Best available estimate, preferring the most precise fiducial present."""
    if not HAVE_CV2 or image is None or image.size == 0:
        return UNKNOWN
    for detector in (
        detect_aruco,
        detect_id_card,
        (lambda img: detect_coin(img, coin)) if coin else None,
    ):
        if detector is None:
            continue
        try:
            if (result := detector(image)) is not None and result.usable:
                return result
        except Exception as exc:
            log.debug("scale detector %s failed: %s", detector, exc)
    return UNKNOWN
