"""Turn an uploaded file into an image the pipeline can read, or refuse it clearly.

Everything here is a guard. An upload endpoint that decodes whatever arrives is the
easiest way to hand a stranger the process, so the type is checked, the size is checked,
and a decode failure is an explicit 400 rather than an array-shaped surprise three
stages downstream.
"""

from __future__ import annotations

import logging

import numpy as np

from app.core.config import settings

log = logging.getLogger(__name__)

try:
    import cv2

    HAVE_CV2 = True
except ImportError:  # pragma: no cover - the API refuses uploads without a decoder
    cv2 = None  # type: ignore[assignment]
    HAVE_CV2 = False


# One product, photographed from every side, plus a listing screenshot. More than this
# is a client looping, not an inspection.
MAX_IMAGES = 8

# Below this the file cannot carry a readable declaration; it is a stray asset or a
# tracking pixel, not a photograph of a package.
MIN_EDGE_PX = 64


class ScanInputError(ValueError):
    """The submission cannot be scanned. Carries a message fit to show an officer."""


def _mb(n: int) -> float:
    return n / (1024 * 1024)


def decode(data: bytes, *, filename: str | None, content_type: str | None) -> np.ndarray:
    """Decode one uploaded photograph to a BGR array.

    The declared content type is checked because it is cheap, and then ignored in favour
    of whether the bytes actually decode — a client can claim anything, and the decoder
    is the only honest witness.
    """
    if not HAVE_CV2:  # pragma: no cover
        raise ScanInputError(
            "This server has no image decoder installed, so photographs cannot be read."
        )
    name = filename or "the uploaded file"

    if content_type and content_type not in settings.allowed_image_types:
        allowed = ", ".join(settings.allowed_image_types)
        raise ScanInputError(f"{name} is {content_type}; only {allowed} can be scanned.")

    if not data:
        raise ScanInputError(f"{name} is empty.")

    if _mb(len(data)) > settings.max_upload_mb:
        raise ScanInputError(
            f"{name} is {_mb(len(data)):.1f} MB; the limit is {settings.max_upload_mb} MB."
        )

    image = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None or image.size == 0:
        raise ScanInputError(
            f"{name} could not be decoded as an image. Re-upload the original photograph "
            "rather than a screenshot of it."
        )

    height, width = image.shape[:2]
    if min(height, width) < MIN_EDGE_PX:
        raise ScanInputError(
            f"{name} is {width}x{height} px, too small to carry a readable declaration."
        )
    return image
