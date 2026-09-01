"""Where submitted photographs live.

A finding is only as good as the image behind it, so the evidence has to outlive the
request that produced it. Files are written under a per-scan prefix and addressed by
storage key, which is the same shape an S3/MinIO backend would use — swapping this for
object storage later means reimplementing three functions, not rewriting the callers.

Images are re-encoded from the decoded array rather than saved as received. That is
deliberate: it strips EXIF, and EXIF on a field inspector's photograph carries their
GPS coordinates and device identifiers. Location belongs on the scan record, where an
officer put it on purpose, not smuggled inside every evidence file.
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np

from app.core.config import settings

log = logging.getLogger(__name__)

try:
    import cv2

    HAVE_CV2 = True
except ImportError:  # pragma: no cover
    cv2 = None  # type: ignore[assignment]
    HAVE_CV2 = False


class StorageError(RuntimeError):
    """The evidence could not be written or read back."""


def key_for(scan_id: str, image_id: str) -> str:
    return f"scans/{scan_id}/{image_id}.png"


def _resolve(storage_key: str) -> Path:
    """Absolute path for a key, refusing anything that climbs out of the store.

    Keys reach this function from the database, and a traversal sequence in one would
    otherwise turn "serve the evidence image" into "serve any file on the host".
    """
    root = Path(settings.storage_dir).resolve()
    path = (root / storage_key).resolve()
    if not path.is_relative_to(root):
        raise StorageError(f"Refusing a storage key that escapes the store: {storage_key!r}")
    return path


def put_image(image: np.ndarray, *, scan_id: str, image_id: str) -> str:
    """Write one photograph and return its storage key."""
    if not HAVE_CV2:  # pragma: no cover
        raise StorageError("No image encoder is installed, so evidence cannot be stored.")
    storage_key = key_for(scan_id, image_id)
    path = _resolve(storage_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(path), image):
        raise StorageError(f"Could not write evidence image to {path}.")
    return storage_key


def put_bytes(data: bytes, *, scan_id: str, name: str) -> str:
    """Store a generated artefact — a report PDF or its JSON — beside its evidence."""
    storage_key = f"scans/{scan_id}/{name}"
    path = _resolve(storage_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return storage_key


def path_of(storage_key: str) -> Path:
    """Filesystem path for a stored image, checked to exist."""
    path = _resolve(storage_key)
    if not path.is_file():
        raise StorageError(f"The evidence image {storage_key!r} is no longer in the store.")
    return path


def delete_scan(scan_id: str) -> None:
    """Remove a scan's evidence. Only for a scan being deleted outright."""
    folder = _resolve(f"scans/{scan_id}")
    if not folder.is_dir():
        return
    for child in folder.iterdir():
        child.unlink()
    folder.rmdir()
