"""Typed view over a ruleset YAML file, plus the input/output types of the engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from app.models.enums import Channel, FindingStatus, Severity

# A readable label yields many text regions. Below this, the scan has not established
# that it is looking at a label, so it cannot testify to what the label omits.
MIN_BLOCKS_TO_ASSERT_ABSENCE = 3

# Block count alone is not enough: a motion-blurred frame can yield a handful of
# low-confidence guesses that clear the count without amounting to a reading of the
# label. Absence also needs the recovered text to have been read with at least this
# mean OCR confidence. The value sits below the mean confidence of every real pack
# photograph in the fixture set (lowest ~0.88) and well above a smeared capture
# (~0.67), so it blocks the latter without muting genuine missing-declaration findings.
MIN_OCR_CONFIDENCE_TO_ASSERT_ABSENCE = 0.75


@dataclass(frozen=True)
class GeometryBand:
    max_cm2: float | None  # None = unbounded top band
    normal_mm: float
    raised_mm: float


@dataclass(frozen=True)
class GeometryTable:
    name: str
    citation: str
    basis: tuple[str, ...]
    bands: tuple[GeometryBand, ...]

    def required_mm(self, pdp_area_cm2: float, raised: bool = False) -> tuple[float, str]:
        """Height required for a panel of this area, and a human label for the band."""
        for band in self.bands:
            if band.max_cm2 is None or pdp_area_cm2 <= band.max_cm2:
                mm = band.raised_mm if raised else band.normal_mm
                upper = "and above" if band.max_cm2 is None else f"up to {band.max_cm2:g} cm²"
                return mm, upper
        # unreachable while the last band is unbounded
        last = self.bands[-1]
        return (last.raised_mm if raised else last.normal_mm), "and above"


@dataclass(frozen=True)
class Exemption:
    id: str
    citation: str
    description: str
    when: dict[str, Any]


@dataclass(frozen=True)
class Rule:
    id: str
    title: str
    citation: str
    check: str
    severity: Severity
    applies_to: tuple[Channel, ...]
    message_fail: str
    remediation: str | None = None
    note: str | None = None
    skip_when_exempt: bool = True
    only_when: dict[str, Any] = field(default_factory=dict)
    # check-specific configuration
    field_key: str | None = None
    field_keys: tuple[str, ...] = ()
    # Parsed attributes this rule requires (check: attribute). Validated against the
    # declaration type at load time, so a mistyped name is a startup error rather
    # than a silent None that reads as a missing declaration.
    attributes: tuple[str, ...] = ()
    flag: str | None = None
    min_mm: float | None = None
    min_mm_raised: float | None = None
    min_ratio: float | None = None


@dataclass(frozen=True)
class RuleSet:
    version: str
    effective_date: date
    description: str
    source: str
    tables: dict[str, GeometryTable]
    exemptions: tuple[Exemption, ...]
    rules: tuple[Rule, ...]

    def table_for_basis(self, basis: str) -> GeometryTable:
        for table in self.tables.values():
            if basis.upper() in table.basis:
                return table
        return self.tables["table_1"]


# --------------------------------------------------------------------------- input


@dataclass
class FieldValue:
    """One extracted declaration, as the engine sees it.

    `raw_text` is evidence — quoted back to the officer and highlighted on the image.
    `parsed` is fact — the typed result of the extractor's single parse, and the only
    thing a rule may judge. Rules that re-read raw_text were the source of every
    false violation this pipeline has produced.
    """

    key: str
    raw_text: str | None = None
    parsed: Any = None  # a app.pipeline.declarations.Declaration
    confidence: float = 0.0
    bbox: list[float] | None = None
    image_id: str | None = None
    glyph_height_mm: float | None = None
    glyph_width_mm: float | None = None

    @property
    def present(self) -> bool:
        return bool(self.raw_text and self.raw_text.strip())

    def attribute(self, name: str) -> Any:
        """One parsed attribute. Raises on an unknown name rather than returning None.

        A silent None would be indistinguishable from a declaration the package does
        not carry, which is exactly the confusion that turns a bad read into a
        fabricated violation.
        """
        if self.parsed is None:
            return None
        return self.parsed.attribute(name)


@dataclass
class ScanContext:
    """Everything the engine needs to judge one scan."""

    channel: Channel = Channel.PHYSICAL
    scan_date: date = field(default_factory=date.today)
    is_imported: bool = False
    category: str | None = None
    fields: dict[str, FieldValue] = field(default_factory=dict)
    # measurement context
    mm_per_px: float | None = None
    pdp_area_cm2: float | None = None
    is_raised: bool = False  # blown / formed / moulded / embossed / perforated
    # semantic judgements from the VLM extractor, e.g. {"misleading_claim": True}
    semantic_flags: dict[str, bool] = field(default_factory=dict)
    # minimum OCR confidence seen across mandatory declarations
    min_field_confidence: float = 1.0
    # how much text the OCR stage actually recovered, across every image
    blocks_read: int = 0
    # mean OCR confidence across every block read, over every image. 1.0 by default so
    # a context built without it (most tests) behaves as before; the runner passes the
    # real figure. Gates absence assertion alongside blocks_read.
    ocr_confidence: float = 1.0

    def get(self, key: str) -> FieldValue | None:
        value = self.fields.get(key)
        return value if value and value.present else None

    @property
    def can_assert_absence(self) -> bool:
        """Whether "this declaration is missing" is a claim this scan can support.

        Not finding a declaration and the declaration not being there are different
        claims, and only the second is a violation. A dark frame, a lens cap or a
        photograph of the wrong side of the pack yields no declarations either, and
        reporting that as a missing-declaration violation would manufacture evidence
        against a product nobody actually looked at. So absence is only assertable
        once the scan has demonstrably read the label at all — enough regions, and
        with enough confidence that those regions are a reading, not guesswork.
        """
        return (
            self.blocks_read >= MIN_BLOCKS_TO_ASSERT_ABSENCE
            and self.ocr_confidence >= MIN_OCR_CONFIDENCE_TO_ASSERT_ABSENCE
            and bool(self.fields)
        )


# --------------------------------------------------------------------------- output


@dataclass
class FindingResult:
    rule_id: str
    title: str
    citation: str
    status: FindingStatus
    severity: Severity
    message: str
    remediation: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)
    evidence_bbox: list[float] | None = None
    evidence_image_id: str | None = None
