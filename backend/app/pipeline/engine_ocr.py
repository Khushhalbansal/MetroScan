"""OCR engines behind one interface.

RapidOCR (PP-OCRv4 weights on onnxruntime) is the default: it runs offline on CPU,
installs without a compiler, and returns per-line polygons — which the Rule 8
measurements depend on. A StubEngine keeps the pipeline testable without weights.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Iterator
from typing import Any, Protocol

import numpy as np

from app.pipeline.ocr import OcrBlock

log = logging.getLogger(__name__)


class OcrEngine(Protocol):
    name: str

    def read(self, image: np.ndarray, image_id: str | None = None) -> list[OcrBlock]: ...


class StubEngine:
    """Returns nothing. Lets the rest of the pipeline run without OCR weights."""

    name = "stub"

    def read(self, image: np.ndarray, image_id: str | None = None) -> list[OcrBlock]:
        return []


class RapidOcrEngine:
    """PP-OCRv4 detection + recognition via onnxruntime."""

    name = "rapidocr/PP-OCRv4"

    def __init__(self) -> None:
        from rapidocr import RapidOCR

        self._ocr = RapidOCR()

    def read(self, image: np.ndarray, image_id: str | None = None) -> list[OcrBlock]:
        if image is None or image.size == 0:
            return []
        result = self._ocr(image)
        return [
            OcrBlock(
                text=str(text).strip(),
                polygon=[[float(x), float(y)] for x, y in np.asarray(box).reshape(-1, 2)],
                confidence=float(score),
                image_id=image_id,
            )
            for box, text, score in _iter_results(result)
            if str(text).strip()
        ]


def _iter_results(result: object) -> Iterator[tuple[Any, Any, Any]]:
    """RapidOCR has returned both a tuple and a result object across versions."""
    if result is None:
        return

    # 3.x: an object exposing boxes / txts / scores
    boxes = getattr(result, "boxes", None)
    txts = getattr(result, "txts", None)
    scores = getattr(result, "scores", None)
    if boxes is not None and txts is not None:
        if scores is None:
            scores = [1.0] * len(txts)
        # zip() would quietly discard the tail of the longer sequence, dropping text
        # that was genuinely detected. If these ever disagree it is a bug worth seeing,
        # so pair what can be paired and say what was lost.
        if not len(boxes) == len(txts) == len(scores):
            log.warning(
                "OCR returned mismatched result lengths (boxes=%d texts=%d scores=%d); "
                "using the first %d.",
                len(boxes), len(txts), len(scores), min(len(boxes), len(txts), len(scores)),
            )
        yield from zip(boxes, txts, scores, strict=False)
        return

    # 1.x: (list_of_[box, text, score], elapsed)
    payload = result[0] if isinstance(result, tuple) else result
    if not isinstance(payload, Iterable):
        log.warning("Unrecognised OCR result type: %s", type(result).__name__)
        return
    for row in payload:
        if len(row) >= 3:
            yield row[0], row[1], row[2]


_engine: OcrEngine | None = None


def get_engine() -> OcrEngine:
    """The process-wide engine. Model load is slow, so it happens once."""
    global _engine
    if _engine is None:
        try:
            _engine = RapidOcrEngine()
            log.info("OCR engine ready: %s", _engine.name)
        except Exception as exc:
            log.warning("RapidOCR unavailable (%s); falling back to the stub engine.", exc)
            _engine = StubEngine()
    return _engine


def set_engine(engine: OcrEngine) -> None:
    """Swap the engine, for tests and for benchmarking alternatives."""
    global _engine
    _engine = engine
