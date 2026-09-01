"""OCR blocks and the document view that lets a text match be traced back to pixels.

The rest of the pipeline never sees raw OCR output. It sees an OcrDocument: one flat
string it can run patterns over, plus `locate()` to turn any character span in that
string back into a bounding box on a specific image. That mapping is what makes the
Rule 8 geometry checks and the evidence overlay possible.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class OcrBlock:
    """One text region as the OCR engine reported it."""

    text: str
    polygon: list[list[float]]  # four [x, y] corners, source-image pixels
    confidence: float
    image_id: str | None = None

    @property
    def bbox(self) -> list[float]:
        # Individual corners can be truncated, not just the corner list, so points are
        # filtered for a usable pair rather than the polygon merely checked for length.
        points = [p for p in self.polygon if len(p) >= 2]
        if not points:
            return [0.0, 0.0, 0.0, 0.0]
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        return [min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)]

    def _edges(self) -> tuple[float, float] | None:
        """Lengths of two adjacent edges, or None if this is not a quadrilateral.

        Blocks can arrive from a different OCR engine or be rehydrated from stored
        JSON, so the four-corner shape is not guaranteed. Unpacking it blindly raised
        ValueError from a property, and OcrDocument.build reads these while ordering
        blocks — outside the runner's per-image guard — so one malformed polygon in a
        stored scan took down the whole re-evaluation.
        """
        if len(self.polygon) < 4 or any(len(p) < 2 for p in self.polygon[:4]):
            return None
        (x0, y0), (x1, y1), (x2, y2), _ = ((p[0], p[1]) for p in self.polygon[:4])
        return (
            ((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5,
            ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5,
        )

    @property
    def height_px(self) -> float:
        """Height along the block's own axis, so rotated text is not over-measured."""
        edges = self._edges()
        if edges is None or min(edges) <= 0:
            return self.bbox[3]
        # the shorter of the two adjacent edges is the text height
        return min(edges)

    @property
    def width_px(self) -> float:
        edges = self._edges()
        if edges is None or max(edges) <= 0:
            return self.bbox[2]
        return max(edges)

    @property
    def centre(self) -> tuple[float, float]:
        x, y, w, h = self.bbox
        return x + w / 2, y + h / 2

    def to_json(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "polygon": self.polygon,
            "confidence": self.confidence,
            "image_id": self.image_id,
        }

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> OcrBlock:
        return cls(
            text=raw["text"],
            polygon=raw["polygon"],
            confidence=raw.get("confidence", 0.0),
            image_id=raw.get("image_id"),
        )


@dataclass
class Span:
    """A character range in OcrDocument.text, resolved back to the page."""

    start: int
    end: int
    blocks: list[OcrBlock]

    @property
    def bbox(self) -> list[float] | None:
        if not self.blocks:
            return None
        xs = [b.bbox[0] for b in self.blocks] + [b.bbox[0] + b.bbox[2] for b in self.blocks]
        ys = [b.bbox[1] for b in self.blocks] + [b.bbox[1] + b.bbox[3] for b in self.blocks]
        return [min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)]

    @property
    def image_id(self) -> str | None:
        return self.blocks[0].image_id if self.blocks else None

    @property
    def confidence(self) -> float:
        return min((b.confidence for b in self.blocks), default=0.0)

    @property
    def height_px(self) -> float | None:
        """Median block height, so one stray tall block does not skew the measurement."""
        if not self.blocks:
            return None
        heights = sorted(b.height_px for b in self.blocks)
        return heights[len(heights) // 2]

    @property
    def char_width_px(self) -> float | None:
        """Mean advance width per character across the span's blocks."""
        total_w = sum(b.width_px for b in self.blocks)
        total_c = sum(max(len(b.text), 1) for b in self.blocks)
        return total_w / total_c if total_c else None


@dataclass
class OcrDocument:
    """All blocks across all images of one scan, flattened into searchable text."""

    blocks: list[OcrBlock] = field(default_factory=list)
    text: str = ""
    # for each character index in `text`, which block it came from (-1 for separators)
    _owner: list[int] = field(default_factory=list, repr=False)

    @classmethod
    def build(cls, blocks: list[OcrBlock], line_tolerance: float = 0.6) -> OcrDocument:
        """Order blocks into reading order per image and join them into one string.

        Detectors routinely split one printed line into several boxes — a price and its
        "(inclusive of all taxes)" rider, or a label and its value. Blocks that share a
        physical line are therefore joined with a space and only a genuine line break
        becomes a newline. Emitting "\\n" between every block instead would tear such a
        declaration in half, and the patterns that read a line at a time would then see
        only a fragment.
        """
        # Blank detections carry no declaration and would open an empty line that the
        # line-oriented patterns then have to step over.
        lines = _reading_order([b for b in blocks if b.text.strip()], line_tolerance)
        ordered: list[OcrBlock] = []
        parts: list[str] = []
        owner: list[int] = []

        for line in lines:
            if parts:
                parts.append("\n")
                owner.append(-1)
            for position, block in enumerate(line):
                if position:
                    parts.append(" ")
                    owner.append(-1)
                parts.append(block.text)
                owner.extend([len(ordered)] * len(block.text))
                ordered.append(block)

        return cls(blocks=ordered, text="".join(parts), _owner=owner)

    def locate(self, start: int, end: int) -> Span:
        """Resolve a character span in `text` back to the blocks that produced it."""
        seen: list[int] = []
        for i in range(max(0, start), min(end, len(self._owner))):
            owner = self._owner[i]
            if owner >= 0 and owner not in seen:
                seen.append(owner)
        return Span(start=start, end=end, blocks=[self.blocks[i] for i in seen])

    def line_containing(self, index: int) -> str:
        """The whole physical line a character sits on — declarations are line-shaped."""
        start = self.text.rfind("\n", 0, index) + 1
        end = self.text.find("\n", index)
        return self.text[start : end if end != -1 else len(self.text)]

    def lines_after(self, index: int, count: int = 3) -> list[str]:
        """The next few lines, for declarations that run on (addresses, mostly)."""
        end = self.text.find("\n", index)
        if end == -1:
            return []
        return [ln for ln in self.text[end + 1 :].split("\n")[:count] if ln.strip()]

    @property
    def mean_confidence(self) -> float:
        if not self.blocks:
            return 0.0
        return sum(b.confidence for b in self.blocks) / len(self.blocks)


def _reading_order(blocks: list[OcrBlock], line_tolerance: float) -> list[list[OcrBlock]]:
    """Group blocks into lines per image, top to bottom, left to right within a line."""
    ordered: list[list[OcrBlock]] = []
    by_image: dict[str | None, list[OcrBlock]] = {}
    for b in blocks:
        by_image.setdefault(b.image_id, []).append(b)

    for image_id in sorted(by_image, key=lambda k: (k is None, k or "")):
        page = sorted(by_image[image_id], key=lambda b: b.centre[1])
        lines: list[list[OcrBlock]] = []
        for block in page:
            _, cy = block.centre
            band = block.height_px * line_tolerance
            for line in lines:
                if abs(line[0].centre[1] - cy) <= band:
                    line.append(block)
                    break
            else:
                lines.append([block])
        for line in lines:
            ordered.append(sorted(line, key=lambda b: b.centre[0]))
    return ordered
