"""Render packaged-commodity labels with known ground truth.

Used three ways: to test the pipeline end to end, to build the injected-violation half
of the evaluation set, and to demonstrate the system without a shelf of real products.

Because the renderer knows the true millimetre size of everything it draws, a label it
produces is a ground truth the measurement chain can be scored against.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from app.pipeline.scale import ARUCO_MARKER_MM

try:
    import cv2

    HAVE_CV2 = True
except ImportError:  # pragma: no cover
    cv2 = None  # type: ignore[assignment]
    HAVE_CV2 = False

# Candidate faces, in preference order. The renderer must not depend on any one being
# installed, so it falls back to PIL's bitmap font and records that it did.
FONT_CANDIDATES = (
    "C:/Windows/Fonts/arial.ttf",
    "C:/Windows/Fonts/segoeui.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
)


@dataclass
class Declaration:
    """One line of the label, with the type size it is drawn at."""

    text: str
    height_mm: float = 2.0
    bold: bool = False


@dataclass
class LabelSpec:
    """A label and the truth about it."""

    width_mm: float = 90.0
    height_mm: float = 120.0
    px_per_mm: float = 12.0
    background: tuple[int, int, int] = (247, 246, 242)
    ink: tuple[int, int, int] = (24, 26, 30)
    with_scale_card: bool = True
    declarations: list[Declaration] = field(default_factory=list)
    # what the label is *supposed* to be, for scoring
    truth: dict[str, object] = field(default_factory=dict)

    @property
    def size_px(self) -> tuple[int, int]:
        return int(self.width_mm * self.px_per_mm), int(self.height_mm * self.px_per_mm)


def _load_font(path_px: float) -> tuple[ImageFont.FreeTypeFont | ImageFont.ImageFont, bool]:
    for candidate in FONT_CANDIDATES:
        if Path(candidate).exists():
            try:
                return ImageFont.truetype(candidate, int(max(path_px, 1))), True
            except OSError:
                continue
    return ImageFont.load_default(), False


def _font_for_cap_height(target_px: float) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Pick the point size whose capital letters are target_px tall.

    Cap height is a fraction of em that varies by face, so it is measured rather than
    assumed, then corrected once — which lands within a pixel for every face tried.
    """
    guess = target_px / 0.716  # a reasonable starting ratio for humanist sans faces
    font, scalable = _load_font(guess)
    if not scalable:
        return font
    box = font.getbbox("H")
    measured = box[3] - box[1]
    if measured > 0:
        corrected = guess * (target_px / measured)
        font, _ = _load_font(corrected)
    return font


def _draw_scale_card(image: Image.Image, spec: LabelSpec) -> None:
    """Stamp the printable 40 mm ArUco marker beside the pack."""
    if not HAVE_CV2:
        return
    side_px = int(ARUCO_MARKER_MM * spec.px_per_mm)
    dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
    marker = cv2.aruco.generateImageMarker(dictionary, 7, side_px)
    card = Image.fromarray(marker).convert("RGB")
    margin = int(4 * spec.px_per_mm)
    image.paste(card, (margin, image.height - side_px - margin))


def render(spec: LabelSpec) -> np.ndarray:
    """Draw the label. Returns a BGR array, as the rest of the pipeline expects."""
    pack_w, pack_h = spec.size_px
    card_px = int(ARUCO_MARKER_MM * spec.px_per_mm) if spec.with_scale_card else 0
    margin = int(6 * spec.px_per_mm)

    canvas_w = pack_w + margin * 2
    canvas_h = pack_h + margin * 2 + (card_px + margin if spec.with_scale_card else 0)
    image = Image.new("RGB", (canvas_w, canvas_h), (235, 235, 232))

    pack = Image.new("RGB", (pack_w, pack_h), spec.background)
    draw = ImageDraw.Draw(pack)

    y = int(6 * spec.px_per_mm)
    for declaration in spec.declarations:
        target_px = declaration.height_mm * spec.px_per_mm
        font = _font_for_cap_height(target_px)
        draw.text((int(5 * spec.px_per_mm), y), declaration.text, font=font, fill=spec.ink)
        try:
            line_h = font.getbbox(declaration.text)[3]
        except AttributeError:  # pragma: no cover - bitmap fallback
            line_h = target_px
        y += int(max(line_h, target_px) + target_px * 0.75)

    image.paste(pack, (margin, margin))
    if spec.with_scale_card:
        _draw_scale_card(image, spec)

    rgb = np.asarray(image)
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR) if HAVE_CV2 else rgb[:, :, ::-1].copy()


# --------------------------------------------------------------------------- presets

COMPLIANT_DECLARATIONS = [
    Declaration("Sunrise Foods", 5.0, bold=True),
    Declaration("Roasted Chana Masala", 3.0),
    Declaration("Manufactured by: Sunrise Foods Private Limited", 2.0),
    Declaration("Plot 14, MIDC Ambad", 2.0),
    Declaration("Nashik, Maharashtra 422010", 2.0),
    Declaration("Net Qty: 200 g", 3.0),
    Declaration("MRP Rs. 45.00", 3.0),
    Declaration("(inclusive of all taxes)", 2.0),
    Declaration("Rs. 0.23 per g", 2.0),
    Declaration("Mfd. 03/2026", 2.0),
    Declaration("Batch No: RC2603A", 2.0),
    Declaration("Consumer Care: Sunrise Foods Pvt Ltd", 2.0),
    Declaration("Plot 14, MIDC Ambad, Nashik 422010", 2.0),
    Declaration("care@sunrisefoods.in", 2.0),
    Declaration("Toll free 1800 200 1234", 2.0),
]


def compliant_label() -> LabelSpec:
    """A pack that satisfies every rule."""
    return LabelSpec(
        declarations=list(COMPLIANT_DECLARATIONS),
        truth={
            "mrp": 45.0,
            "net_quantity": (200.0, "g"),
            "net_quantity_height_mm": 3.0,
            "expect_verdict": "COMPLIANT",
        },
    )


def label_with(violations: set[str]) -> LabelSpec:
    """A pack with specific violations injected, for scoring the rule engine.

    Supported: undersized_net_quantity, missing_mrp, no_tax_phrase, dual_mrp,
    missing_consumer_care_email, missing_mfg_date, missing_manufacturer.
    """
    lines = list(COMPLIANT_DECLARATIONS)

    def drop(predicate) -> None:
        nonlocal lines
        lines = [d for d in lines if not predicate(d)]

    if "undersized_net_quantity" in violations:
        lines = [
            Declaration(d.text, 1.0 if d.text.startswith("Net Qty") else d.height_mm, d.bold)
            for d in lines
        ]
    if "missing_mrp" in violations:
        drop(lambda d: "MRP" in d.text or "inclusive of all taxes" in d.text)
    if "no_tax_phrase" in violations:
        drop(lambda d: "inclusive of all taxes" in d.text)
    if "dual_mrp" in violations:
        lines.insert(
            next(i for i, d in enumerate(lines) if "MRP" in d.text) + 1,
            Declaration("MRP Rs. 50.00", 3.0),
        )
    if "missing_consumer_care_email" in violations:
        drop(lambda d: "@" in d.text)
    if "missing_mfg_date" in violations:
        drop(lambda d: d.text.startswith("Mfd."))
    if "missing_manufacturer" in violations:
        drop(lambda d: d.text.startswith("Manufactured by"))

    return LabelSpec(
        declarations=lines,
        truth={"violations": sorted(violations), "expect_verdict": "NON_COMPLIANT"},
    )


def save(image: np.ndarray, path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if HAVE_CV2:
        cv2.imwrite(str(path), image)
    else:  # pragma: no cover
        Image.fromarray(image[:, :, ::-1]).save(path)
    return path
