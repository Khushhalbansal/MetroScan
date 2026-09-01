"""Draw findings onto the photograph they were decided from.

An annotated image is what makes a report checkable by someone who was not there. The
box says which marks on the pack the finding is about; without it, "the net quantity
numerals are 1.4 mm" is a claim the reader has to take on trust.

Boxes are drawn only where a finding actually cited a region. Nothing is inferred, and
a finding with no evidence produces no box rather than a box somewhere plausible.
"""

from __future__ import annotations

import logging

import numpy as np

from app.models.enums import FindingStatus

log = logging.getLogger(__name__)

try:
    import cv2

    HAVE_CV2 = True
except ImportError:  # pragma: no cover
    cv2 = None  # type: ignore[assignment]
    HAVE_CV2 = False


# The palette from docs/design-direction.md, in BGR because that is what OpenCV wants.
# Status is never carried by colour alone here either: every box gets its rule id, so
# the annotation survives greyscale printing and a photocopied inspection file.
COLOURS: dict[FindingStatus, tuple[int, int, int]] = {
    FindingStatus.FAIL: (40, 59, 169),  # oxide  #A93B28
    FindingStatus.NEEDS_REVIEW: (46, 124, 166),  # brass  #A67C2E
    FindingStatus.PASS: (93, 106, 44),  # patina #2C6A5D
}
CHASSIS = (28, 25, 22)  # #16191C
BONE = (242, 245, 244)  # #F4F5F2


def _thickness(image: np.ndarray) -> int:
    """Scale line weight to the image, so a 4000px photo is not hairlined."""
    return max(2, int(round(min(image.shape[:2]) / 400)))


def annotate(
    image: np.ndarray,
    boxes: list[tuple[list[float], FindingStatus, str]],
) -> np.ndarray:
    """Return a copy of `image` with one labelled box per finding.

    `boxes` is (bbox, status, label) where bbox is [x, y, w, h] in source pixels.
    """
    if not HAVE_CV2 or image is None or image.size == 0:
        return image

    canvas = image.copy()
    weight = _thickness(canvas)
    height, width = canvas.shape[:2]
    font_scale = max(0.4, min(width, height) / 1600)

    # Failures last, so their boxes sit on top where findings overlap on the same
    # declaration — the violation is the thing the reader must not miss.
    order = {FindingStatus.PASS: 0, FindingStatus.NEEDS_REVIEW: 1, FindingStatus.FAIL: 2}
    for bbox, status, label in sorted(boxes, key=lambda b: order.get(b[1], 0)):
        if not bbox or len(bbox) < 4:
            continue
        x, y, w, h = (int(round(v)) for v in bbox[:4])
        if w <= 0 or h <= 0:
            continue
        # Clamp to the frame: a bbox from a re-encoded or rotated image can sit
        # partly outside it, and cv2 silently draws nothing rather than complaining.
        x0, y0 = max(0, x), max(0, y)
        x1, y1 = min(width - 1, x + w), min(height - 1, y + h)
        if x1 <= x0 or y1 <= y0:
            continue

        colour = COLOURS.get(status, CHASSIS)
        cv2.rectangle(canvas, (x0, y0), (x1, y1), colour, weight)

        if not label:
            continue
        (text_w, text_h), baseline = cv2.getTextSize(
            label, cv2.FONT_HERSHEY_DUPLEX, font_scale, 1
        )
        # Tag above the box, or below it when the box is at the top of the frame.
        tag_bottom = y0 - weight if y0 - text_h - baseline - weight > 0 else y1 + text_h + baseline
        tag_top = tag_bottom - text_h - baseline
        cv2.rectangle(
            canvas,
            (x0, max(0, tag_top)),
            (min(width - 1, x0 + text_w + 8), max(0, tag_bottom)),
            colour,
            -1,
        )
        cv2.putText(
            canvas,
            label,
            (x0 + 4, max(text_h, tag_bottom - baseline // 2)),
            cv2.FONT_HERSHEY_DUPLEX,
            font_scale,
            BONE,
            1,
            cv2.LINE_AA,
        )
    return canvas


def to_png(image: np.ndarray) -> bytes:
    if not HAVE_CV2:  # pragma: no cover
        raise RuntimeError("No image encoder available.")
    ok, buffer = cv2.imencode(".png", image)
    if not ok:
        raise RuntimeError("Could not encode the annotated evidence image.")
    return bytes(buffer)
