"""Locate the Rule 6 declarations inside an OCR document.

Deterministic, offline and inspectable: every value carries the character span it came
from, so the UI can point at the pixels and an officer can check the machine's work.
Patterns follow how Indian packs are actually printed, not how the rules phrase things.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass

from app.models.enums import FieldKey
from app.pipeline.declarations import (
    AddressDeclaration,
    DateDeclaration,
    Declaration,
    EmailDeclaration,
    NameDeclaration,
    OriginDeclaration,
    PhoneDeclaration,
    PriceDeclaration,
    QuantityDeclaration,
    UnitPriceDeclaration,
)
from app.pipeline.ocr import OcrDocument, Span
from app.rules import units

# OCR routinely confuses these inside otherwise-numeric strings.
_DIGIT_LOOKALIKES = str.maketrans({"O": "0", "o": "0", "l": "1", "I": "1", "|": "1", "S": "5"})

# Regex alternation takes the first branch that matches, not the longest, so units must
# be offered longest-first or "g" would match the head of "gms".
#
# This was built by string-replacing "m2" into "m2|m²" over the joined alternation,
# which also rewrote the "m2" *inside* "cm2" and produced "cm2|m²|cm²" — a stray
# alternative spliced into the middle of the ordering. Superscript forms are now added
# as units before the ordering is applied, so the invariant holds by construction.
_UNIT_WORDS = {*units.UNITS, *units.ALIASES}
_UNIT_WORDS |= {w[:-1] + "²" for w in _UNIT_WORDS if w.endswith("2")}
_UNIT_ALTERNATION = "|".join(
    re.escape(w) for w in sorted(_UNIT_WORDS, key=lambda w: (-len(w), w))
)

_CURRENCY = r"(?:₹|Rs\.?|INR|R5\.?)"

# Two branches, and the comma-grouped one requires an actual comma. With `*` instead
# of `+` it also matches the leading three digits of an ungrouped run and, because
# alternation stops at the first success, "45000" was captured as "450" — a
# hundredfold error on any appliance or electronics pack that prints its MRP without
# Indian digit grouping. The `+` forces such a price down to the plain-digits branch.
_AMOUNT = r"\d{1,3}(?:,\d{2,3})+(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?"


@dataclass
class Extraction:
    """One located declaration.

    `raw_text` is evidence — quoted to the officer and highlighted on the image.
    `parsed` is fact — the only thing rules are permitted to judge. See
    app.pipeline.declarations for why the two are kept apart.
    """

    key: str
    raw_text: str
    parsed: Declaration
    span: Span
    confidence: float

    @property
    def bbox(self) -> list[float] | None:
        return self.span.bbox

    @property
    def image_id(self) -> str | None:
        return self.span.image_id


def _clean_amount(text: str) -> float | None:
    try:
        return float(text.translate(_DIGIT_LOOKALIKES).replace(",", "").strip())
    except (ValueError, AttributeError):
        return None


def _iter(pattern: str, doc: OcrDocument, flags: int = re.I) -> Iterator[re.Match[str]]:
    return re.finditer(pattern, doc.text, flags)


def _confidence(span: Span, penalty: float = 0.0) -> float:
    return max(0.0, min(1.0, span.confidence - penalty))


def _pick_clearest(doc: OcrDocument, matches: list[re.Match[str]]) -> re.Match[str] | None:
    """The match read with the highest confidence, ties going to the earliest.

    A declaration is routinely captured on several of a scan's images — sharp on one,
    smeared on another. Taking the first occurrence in reading order let a blurred
    panel override a clean one purely because its image sorted earlier. Reconcile by
    confidence instead: give every field the benefit of the clearest photograph it
    appears in.
    """
    if not matches:
        return None
    return max(matches, key=lambda m: (doc.locate(m.start(), m.end()).confidence, -m.start()))


# --------------------------------------------------------------------------- MRP

_MRP_LABEL = r"(?:M\.?\s?R\.?\s?P\.?|Maximum\s+Retail\s+Price|Retail\s+Sale\s+Price|MRP)"
# `junk` absorbs a stray digit sitting between "MRP" and its colon — an OCR misread of
# the ₹ glyph, which recognisers routinely turn into a "3" or an "8" glued to the label
# ("MRP3:"). Without it the "3" is taken as the price and the real figure a few
# characters on ("229.00") is never looked at. Gated on a following ":" or "-" so a
# legitimately glued price like "MRP45.00" keeps its amount.
_MRP = re.compile(
    rf"{_MRP_LABEL}\s*(?:(?P<junk>[0-9])\s*(?=[:\-]))?\s*[:\-]?\s*"
    rf"(?P<currency>{_CURRENCY})?\s*(?P<amount>{_AMOUNT})",
    re.I,
)
_MRP_LABEL_ONLY = re.compile(_MRP_LABEL, re.I)
# Any currency token, searched across the whole MRP evidence line rather than only
# immediately before the chosen figure. On a stamped-value pack the printed "MRP ₹"
# and the ink figure land in different cells, and the only intact marking may be a
# "Rs." on a per-gram price further along the same row. The letter guard keeps "rs"
# inside a word ("Mrs", "firstquality") from reading as a rupee mark.
_CURRENCY_MARK = re.compile(rf"(?<![A-Za-z]){_CURRENCY}", re.I)
# A price written "Rs 0.55/g" or "45 per kg" is a unit sale price, not a retail price.
# Reading it as the MRP put a per-gram figure where the rupee price belonged: it drove
# a false dual-MRP finding and a nonsense unit-price cross-check. Excluded from both.
_PER_UNIT_SUFFIX = re.compile(rf"\s*(?:/|per)\s*(?:{_UNIT_ALTERNATION}|piece|pcs?)\b", re.I)
# A currency-marked amount carrying no MRP label of its own — used only as a fallback
# when a price table is flattened so the heading and the figure land on different lines.
_PRICE_TOKEN = re.compile(rf"(?P<currency>{_CURRENCY})\s*(?P<amount>{_AMOUNT})", re.I)
# A bare amount, no currency. Used only on a bare MRP heading's own line, where a
# printed-form label ("MRP (Rs) incl. of all taxes") sets the figure past its rider
# with no mark of its own.
_AMOUNT_TOKEN = re.compile(_AMOUNT)
# The rider beneath the price. OCR frequently breaks "inclusive" apart ("inclu" /
# "sive"), so "of all taxes" on its own — which only ever occurs as the tail of this
# phrase on a retail pack — is accepted; a bare "all taxes" is not.
_TAX_PHRASE = re.compile(r"(?:incl\w*\.?\s*(?:of\s+)?|of\s+)all\s+tax(?:es)?", re.I)
# How far below the price to look for its "inclusive of all taxes" rider.
_TAX_PHRASE_LOOKAHEAD_LINES = 3
# How far past a bare "MRP" heading to look for the figure it heads, when nothing
# parsed as a labelled price. Wider than the tax lookahead because a price table
# interleaves unrelated cells; the fallback is penalised and must carry a currency mark.
_MRP_FIGURE_LOOKAHEAD_LINES = 5


def _line_starts(text: str) -> list[int]:
    starts, pos = [], 0
    for line in text.split("\n"):
        starts.append(pos)
        pos += len(line) + 1
    return starts


def _line_index(starts: list[int], char_index: int) -> int:
    lo, hi = 0, max(0, len(starts) - 1)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if starts[mid] <= char_index:
            lo = mid
        else:
            hi = mid - 1
    return lo


# A printed-form label with no value the extractor could read beside it. On this
# layout the label ("Date of Mfg.:", "USP ₹:") is set static and the value is stamped
# into a separate column; when OCR garbles the stamp the value is simply gone from the
# text. That is "label present, value unreadable" — the same class as the lens-cap
# guard, one field down: a printed label is positive evidence the declaration exists,
# so the presence rule must send it to an officer, never call it missing and never
# pass it. The stub below carries the label line as evidence at a deliberately low
# confidence, which routes the presence check to NEEDS_REVIEW.
_LABEL_ONLY_CONFIDENCE = 0.25


def _label_only_stub(
    doc: OcrDocument, label: re.Match[str], key: str, parsed: Declaration
) -> Extraction:
    start = doc.text.rfind("\n", 0, label.start()) + 1
    end = doc.text.find("\n", label.end())
    end = end if end != -1 else len(doc.text)
    span = doc.locate(start, end)
    return Extraction(
        key=key,
        raw_text=doc.text[start:end].strip() or label.group(0).strip(),
        parsed=parsed,
        span=span,
        confidence=_LABEL_ONLY_CONFIDENCE,
    )


def _tax_rider_near(doc: OcrDocument, price_matches: list[re.Match[str]]) -> bool:
    """Whether an inclusive-of-taxes rider sits on, or a few lines below, any price.

    Evaluated per price rather than only for the one chosen as primary: the rider
    routinely follows the *last* price in a stacked "USE BY / MRP / per g" block, which
    is not the one the extractor reports.
    """
    lines = doc.text.split("\n")
    starts = _line_starts(doc.text)
    for m in price_matches:
        first = _line_index(starts, m.start())
        window = "\n".join(lines[first : first + _TAX_PHRASE_LOOKAHEAD_LINES + 1])
        if _TAX_PHRASE.search(window):
            return True
    return False


def _mrp_figure_below_label(
    doc: OcrDocument,
) -> tuple[float | None, str | None, int, int, float] | None:
    """A figure tied to a bare MRP heading: (amount, mark, start, end, penalty).

    Two shapes, penalised by how positional the link to the heading is:
      * a currency-marked amount on any of the next few lines — a price table whose
        heading and figure were flattened onto different rows (0.45);
      * on the heading's *own* line, a bare amount sitting past an "(Rs) incl. of all
        taxes" rider that carries no mark of its own (0.15 — still one printed row).
        Confined to that line: a bare number further down is as often a batch code or
        a net weight as a price.
    """
    label = _MRP_LABEL_ONLY.search(doc.text)
    if label is None:
        return None
    offset = label.end()
    lines = doc.text[offset : offset + 320].split("\n")[: _MRP_FIGURE_LOOKAHEAD_LINES + 1]
    for i, line in enumerate(lines):
        token = _PRICE_TOKEN.search(line)
        if token and not _PER_UNIT_SUFFIX.match(line, token.end()):
            return (
                _clean_amount(token.group("amount")),
                token.group("currency") or None,
                offset + token.start(),
                offset + token.end(),
                0.45,
            )
        if i == 0:
            bare = _AMOUNT_TOKEN.search(line)
            if bare and not _PER_UNIT_SUFFIX.match(line, bare.end()):
                return (
                    _clean_amount(bare.group()),
                    None,
                    offset + bare.start(),
                    offset + bare.end(),
                    0.15,
                )
        offset += len(line) + 1
    return None


def extract_mrp(doc: OcrDocument) -> Extraction | None:
    text = doc.text
    labelled = list(_MRP.finditer(text))

    # A labelled price written "per <unit>" is a unit sale price, not a retail price.
    retail = [m for m in labelled if not _PER_UNIT_SUFFIX.match(text, m.end())]
    amounts: list[float] = [
        v for m in retail if (v := _clean_amount(m.group("amount"))) is not None
    ]

    penalty = 0.0
    primary = _pick_clearest(doc, retail)
    if primary is not None:
        start = text.rfind("\n", 0, primary.start()) + 1
        end = text.find("\n", primary.end())
        end = end if end != -1 else len(text)
        amount = _clean_amount(primary.group("amount"))
        currency = primary.group("currency") or None
    else:
        # The label and the figure were flattened onto different lines. Accept a
        # currency-marked amount just below the heading, penalised: the link between
        # them is positional, not punctuational.
        figure = _mrp_figure_below_label(doc)
        if figure is None:
            return None
        amount, currency, fig_start, fig_end, penalty = figure
        start = text.rfind("\n", 0, fig_start) + 1
        end = text.find("\n", fig_end)
        end = end if end != -1 else len(text)
        if amount is not None:
            amounts.append(amount)

    # Widen the evidence span to take in a rider on a nearby following line.
    if not _TAX_PHRASE.search(text[start:end]):
        probe = end
        for _ in range(_TAX_PHRASE_LOOKAHEAD_LINES):
            if probe >= len(text):
                break
            line_end = text.find("\n", probe + 1)
            line_end = line_end if line_end != -1 else len(text)
            if _TAX_PHRASE.search(text[probe:line_end]):
                end = line_end
                break
            probe = line_end

    # The figure the extractor picked may carry no mark of its own — the ₹ was misread,
    # or it sits in a different cell from the ink value. A ₹/Rs/INR anywhere on the MRP
    # row is still the pack marking its price, which is what Rule 6(1)(e) asks.
    if currency is None:
        mark = _CURRENCY_MARK.search(text[start:end])
        if mark:
            currency = mark.group(0)

    span = doc.locate(start, end)
    return Extraction(
        key=FieldKey.MRP,
        raw_text=text[start:end].strip(),
        parsed=PriceDeclaration(
            amount=amount,
            all_amounts=tuple(sorted(set(amounts))),
            # What was actually printed, not a constant. This used to be "INR"
            # unconditionally, which asserted a rupee marking on packs that carried
            # none — so it could not be used to judge Rule 6(1)(e) at all.
            currency_mark=currency,
            inclusive_of_taxes=bool(_TAX_PHRASE.search(text[start:end]))
            or _tax_rider_near(doc, labelled),
        ),
        span=span,
        confidence=_confidence(span, penalty),
    )


# --------------------------------------------------------------------- net quantity

_NET_LABEL = (
    r"(?:Net\s*(?:Qty|Quantity|Wt\.?|Weight|Content[s]?|Vol(?:ume)?\.?)|"
    r"Net|Qty|Quantity|Contents?)"
)
_NET_QTY = re.compile(
    rf"{_NET_LABEL}\s*[:\-]?\s*(?P<value>{_AMOUNT})\s*(?P<unit>{_UNIT_ALTERNATION})\b",
    re.I,
)
# fallback: a bare "200 g" with no label at all, which small packs often carry. Only
# mass and volume units qualify here: a bare number with "n" / "No" / "pcs" is far
# more often a serving count or a nutrition-panel row than a net quantity, and with no
# "Net Qty" label there is nothing to tell them apart. Reading "178.5 No" out of a
# nutrition table as the net quantity is what drove a bogus unit-price cross-check.
_BARE_QTY_UNIT = "|".join(
    re.escape(w)
    for w in sorted(
        {
            u
            for u in _UNIT_WORDS
            if units.basis_of(u) in (units.Basis.WEIGHT, units.Basis.VOLUME)
        },
        key=lambda w: (-len(w), w),
    )
)
_BARE_QTY = re.compile(rf"\b(?P<value>{_AMOUNT})\s*(?P<unit>{_BARE_QTY_UNIT})\b", re.I)


def extract_net_quantity(doc: OcrDocument) -> Extraction | None:
    # A labelled "Net Qty …" is trustworthy, so take the clearest read of it across the
    # images. A bare quantity is not: keep to the first one in reading order — packs
    # print the net quantity on the front panel, above the nutrition and serving-size
    # figures that share its shape.
    match = _pick_clearest(doc, list(_NET_QTY.finditer(doc.text)))
    penalty = 0.0
    if match is None:
        match = _BARE_QTY.search(doc.text)
        penalty = 0.25
    if match is None:
        return None

    value = _clean_amount(match.group("value"))
    unit = units.canonical(match.group("unit")) or match.group("unit").lower()
    span = doc.locate(match.start(), match.end())
    return Extraction(
        key=FieldKey.NET_QUANTITY,
        raw_text=match.group(0).strip(),
        parsed=QuantityDeclaration(
            value=value,
            unit=units.canonical(unit),
            basis=units.basis_of(unit),
            unlabelled=bool(penalty),
        ),
        span=span,
        confidence=_confidence(span, penalty),
    )


# ----------------------------------------------------------------------- mfg date

_MFG_LABEL = (
    r"(?:Mfg|Mfd|MFG|MFD|Manufactured|Manufacturing|Packed|Pkd|PKD|Date\s+of\s+"
    r"(?:Manufacture|Manufacturing|Packing|Import)|Mfg\.?\s*Date|Packaged)"
)
_MFG_DATE = re.compile(
    rf"{_MFG_LABEL}\s*(?:on|date)?\s*[:\-.]?\s*"
    r"(?P<date>(?:\d{1,2}|Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[A-Za-z]*"
    r"\s*[/\-. ]\s*\d{2,4})",
    re.I,
)
# Only the headings that are unambiguously about a *date* drive the detached-value
# fallback below. The generic list above also contains "Manufactured" / "Packed",
# which are company-role words too — scanning the lines after those for any number
# adopted an MRP figure as a manufacture date on a pack that declared no date at all.
_MFG_DATE_LABEL_ONLY = re.compile(
    r"\b(?:MFD|MFG\.?\s*D(?:ate|t)?|Mfg\.?\s*Date|PKD|Pkd\.?\s*on|Packed\s*on|Packaged\s*on|"
    r"Date\s+of\s+(?:Manufacture|Manufacturing|Mfg|Mfd|Packing|Packaging|Import))\b",
    re.I,
)
# A numeric date: d/m/y ("15/01/27"), or m/y with a slash or dash ("03/26"), or
# m.yyyy ("07.2026"). The dot form demands a full year so a price like "45.00" — which
# can sit within a few lines of an "MFD" heading — is not read as January of year 45.
_BARE_DATE = re.compile(
    r"(?<!\d)(?:"
    r"\d{1,2}[/\-.]\d{1,2}[/\-.]\d{2,4}"
    r"|\d{1,2}[/\-]\d{2,4}"
    r"|\d{1,2}\.\d{4}"
    r")(?!\d)"
)
# How far past a lone "MFD"/"PKD" label to look for the date it heads. Packs print the
# two in a table — label as a column head, value in the cell below — and the flattened
# reading order puts several unrelated cells between them.
_MFG_DATE_LOOKAHEAD_LINES = 5

_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1
)}

# A manufacture stamp can only fall in a sane window. Used to reject a numeric code
# whose first six digits happen to look like a DDMMYY.
_PLAUSIBLE_YEARS = range(2015, 2036)


def _loose_dmy(text: str) -> DateDeclaration:
    """A day/month/year recovered from noisy stamp text: "30/10/25", "30-10-2025",
    a bare "DDMMYY" run, or "DDMMYY" with a time stuck onto it ("301025 07:38").

    Deliberately permissive about the surrounding characters — an ink stamp OCR's
    with a garbled prefix and a trailing time as often as not — but strict about the
    date itself: DD and MM must both be in range and the year plausible, which is
    what stops a lot number or a barcode segment from being read as a date.
    """
    sep = re.search(r"(?<!\d)(\d{1,2})[/\-. ](\d{1,2})[/\-. ](\d{2,4})(?!\d)", text)
    if sep:
        parsed = _parse_month_year("/".join(sep.groups()))
        if parsed.month:
            return parsed
    for run in re.finditer(r"(?<!\d)(\d{2})(\d{2})(\d{2})", text):
        dd, mm, yy = (int(g) for g in run.groups())
        year = yy + 2000 if yy < 100 else yy
        if 1 <= dd <= 31 and 1 <= mm <= 12 and year in _PLAUSIBLE_YEARS:
            return DateDeclaration(month=mm, year=year)
    return DateDeclaration()


def _date_in_value_column(doc: OcrDocument, label: re.Match[str]) -> Extraction | None:
    """A stamped date whose value column drifted out of line with its heading — a
    tilted print, an off-square photo — so the flattened reading order never put it
    on the heading's line.

    Read by geometry instead: among the blocks sitting to the right of the heading
    and within a few line-heights of it, take the nearest one whose text yields a
    real day *and* month. A block that gives only a year, or whose DD/MM are out of
    range, is passed over — which is how the wrong cell (a use-by date that shifted
    up into this row) and a lot number both get skipped.
    """
    label_blocks = doc.locate(label.start(), label.end()).blocks
    if not label_blocks:
        return None
    anchor = label_blocks[0]
    _, ay = anchor.centre
    band = max(anchor.height_px, 20.0) * 4.5
    right_of_label = anchor.bbox[0] + anchor.bbox[2] - 4.0

    near = sorted(
        (
            b
            for b in doc.blocks
            if all(b is not lb for lb in label_blocks)
            and b.centre[0] >= right_of_label
            and abs(b.centre[1] - ay) <= band
        ),
        key=lambda b: abs(b.centre[1] - ay),
    )
    for block in near:
        found = _loose_dmy(block.text)
        if found.month:
            line_start = doc.text.rfind("\n", 0, label.start()) + 1
            span = doc.locate(line_start, label.end())
            return Extraction(
                key=FieldKey.MFG_DATE,
                raw_text=f"{doc.text[line_start:label.end()].strip()}  {block.text.strip()}",
                parsed=found,
                # Positional, not punctuational — weaker than a one-string match, but
                # a valid DD/MM next to the right heading is real evidence.
                span=span,
                confidence=_confidence(span, 0.2),
            )
    return None


def _parse_month_year(text: str) -> DateDeclaration:
    """Parse a manufacture date once, here.

    Rule 6(1)(d) asks for a month and a year, and MFG_DATE_FORMAT used to decide that
    by running a second regex over the raw text — a separate parser that could disagree
    with this one. It now reads `month` and `year` off this result instead.
    """
    parts = re.split(r"[/\-. ]+", text.strip())
    if len(parts) < 2:
        return DateDeclaration()
    head, tail = parts[0].lower(), parts[-1]
    month = _MONTHS.get(head[:3]) if head[:3].isalpha() else (int(head) if head.isdigit() else None)
    # A three-field all-numeric date is day/month/year when the first field cannot be a
    # month — Indian packs print "15/01/27" for 15 January 2027. Read the month from the
    # middle field in that case rather than rejecting it as out of range.
    if (
        len(parts) >= 3
        and all(p.isdigit() for p in parts)
        and (month is None or month > 12)
        and 1 <= int(parts[1]) <= 12
    ):
        month = int(parts[1])
    if not tail.isdigit():
        return DateDeclaration()
    year = int(tail)
    if year < 100:
        year += 2000
    if month is not None and 1 <= month <= 12:
        return DateDeclaration(month=month, year=year)
    return DateDeclaration(year=year)


def extract_mfg_date(doc: OcrDocument) -> Extraction | None:
    match = _pick_clearest(doc, list(_MFG_DATE.finditer(doc.text)))
    if match is not None:
        start = doc.text.rfind("\n", 0, match.start()) + 1
        span = doc.locate(start, match.end())
        return Extraction(
            key=FieldKey.MFG_DATE,
            raw_text=doc.text[start : match.end()].strip(),
            parsed=_parse_month_year(match.group("date")),
            span=span,
            confidence=_confidence(span),
        )

    # No date sat next to the label. For each manufacture-date heading, look a few
    # flattened lines on for a date-shaped token: enough to recover a genuinely
    # photographed declaration a table layout tore from its heading ("MFD" as a column
    # head, "15/01/27" in the cell below), without reaching so far it adopts an
    # unrelated number. Every heading is tried — the first one is often a QR-code
    # pointer ("Manufactured by: scan to identify the unit") carrying no date at all.
    label_seen: re.Match[str] | None = None
    for label in _MFG_DATE_LABEL_ONLY.finditer(doc.text):
        label_seen = label_seen or label
        offset = label.end()
        for line in doc.text[offset : offset + 320].split("\n")[: _MFG_DATE_LOOKAHEAD_LINES + 1]:
            found = _BARE_DATE.search(line)
            if found:
                line_start = doc.text.rfind("\n", 0, label.start()) + 1
                end = offset + found.end()
                span = doc.locate(line_start, end)
                return Extraction(
                    key=FieldKey.MFG_DATE,
                    raw_text=doc.text[line_start:end].strip(),
                    parsed=_parse_month_year(found.group(0)),
                    # The label-to-value link is inferred from proximity, not
                    # punctuation, so this is weaker evidence than a one-string match.
                    span=span,
                    confidence=_confidence(span, 0.2),
                )
            offset += len(line) + 1

    # Nothing on the lines after any heading. Before giving up, try to associate a
    # value by position rather than by reading order — the printed-form case where a
    # tilt or an off-square photo pushed the stamp column out of line with its labels.
    if label_seen is not None:
        by_geometry = _date_in_value_column(doc, label_seen)
        if by_geometry is not None:
            return by_geometry
        # A manufacture-date label is printed on the pack, but no date read anywhere
        # near it — the stamped value did not survive OCR. Present but unreadable: an
        # officer decides, the rule never fails on it.
        return _label_only_stub(doc, label_seen, FieldKey.MFG_DATE, DateDeclaration())
    return None


# ------------------------------------------------------------------ consumer care

_CARE_LABEL = re.compile(
    r"(?:Consumer|Customer)\s+(?:Care|Complaint|Service|Grievance)[^\n]*|"
    r"For\s+(?:any\s+)?(?:queries|complaints|feedback)[^\n]*|Grievance\s+Officer[^\n]*",
    re.I,
)
_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
# Whether the captured address is well formed is decided here, once, so
# CONSUMER_CARE_EMAIL_VALID reads a parsed answer instead of re-matching the text.
_EMAIL_EXACT = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")


def _valid_email(text: str) -> str | None:
    candidate = text.strip().lower()
    return candidate if _EMAIL_EXACT.match(candidate) else None
_PHONE = re.compile(
    r"(?:1800[\s\-]?\d{3}[\s\-]?\d{3,4}"          # toll free
    r"|\+?91[\s\-]?\d{5}[\s\-]?\d{5}"              # mobile with country code
    r"|\b0\d{2,4}[\s\-]?\d{6,8}\b"                 # landline with STD
    r"|\b[6-9]\d{9}\b)"                            # bare mobile
)


def extract_consumer_care(doc: OcrDocument) -> list[Extraction]:
    out: list[Extraction] = []

    if label := _CARE_LABEL.search(doc.text):
        span = doc.locate(label.start(), label.end())
        out.append(
            Extraction(
                key=FieldKey.CONSUMER_CARE_NAME,
                raw_text=label.group(0).strip(),
                parsed=NameDeclaration(text=label.group(0).strip()),
                span=span,
                confidence=_confidence(span),
            )
        )
        # The address usually runs on beneath the heading.
        following = doc.lines_after(label.start(), 3)
        address = " ".join(
            ln for ln in following if not _EMAIL.search(ln) and not _PHONE.search(ln)
        )
        if address.strip() and re.search(r"\d", address):
            end = label.end()
            for _ in range(3):
                nxt = doc.text.find("\n", end + 1)
                if nxt == -1:
                    break
                end = nxt
            addr_span = doc.locate(label.end(), end)
            out.append(
                Extraction(
                    key=FieldKey.CONSUMER_CARE_ADDRESS,
                    raw_text=address.strip(),
                    parsed=AddressDeclaration(pin=_pin(address)),
                    span=addr_span,
                    confidence=_confidence(addr_span, 0.1),
                )
            )

    if email := _EMAIL.search(doc.text):
        span = doc.locate(email.start(), email.end())
        out.append(
            Extraction(
                key=FieldKey.CONSUMER_CARE_EMAIL,
                raw_text=email.group(0).strip().lower(),
                parsed=EmailDeclaration(address=_valid_email(email.group(0))),
                span=span,
                confidence=_confidence(span),
            )
        )

    if phone := _PHONE.search(doc.text):
        span = doc.locate(phone.start(), phone.end())
        out.append(
            Extraction(
                key=FieldKey.CONSUMER_CARE_PHONE,
                raw_text=phone.group(0).strip(),
                parsed=PhoneDeclaration(digits=re.sub(r"\D", "", phone.group(0))),
                span=span,
                confidence=_confidence(span),
            )
        )

    # Rule 6(1)(f) is one paragraph — "Consumer Service Manager, <company>, <address>,
    # Email: …, Call us at: …". OCR mangles the heading ("CarsimlerServiceManager") so
    # the narrow label pattern misses it while the email and phone, which have their own
    # shapes, are still found. When that happens, recover the name and the address from
    # the block around the contact point rather than reporting them absent.
    keys = {e.key for e in out}
    anchor = email.start() if email else (phone.start() if phone else None)
    if anchor is not None:
        starts = _line_starts(doc.text)
        anchor_line = _line_index(starts, anchor)

        if FieldKey.CONSUMER_CARE_NAME not in keys:
            window = doc.text[max(0, anchor - 400) : anchor + 160]
            if person := _CONTACT_PERSON.search(window):
                idx = doc.text.find(person.group(0), max(0, anchor - 400))
                p_span = (
                    doc.locate(idx, idx + len(person.group(0)))
                    if idx >= 0
                    else doc.locate(anchor, anchor + 1)
                )
                out.append(
                    Extraction(
                        key=FieldKey.CONSUMER_CARE_NAME,
                        raw_text=person.group(0).strip(),
                        parsed=NameDeclaration(text=person.group(0).strip()),
                        span=p_span,
                        confidence=_confidence(p_span, 0.2),
                    )
                )

        if FieldKey.CONSUMER_CARE_ADDRESS not in keys:
            block = _best_address_block(doc)
            # Only if it is the same contiguous block as the contact point, so a distant
            # manufacturer address is not misattributed to consumer care.
            if block is not None and abs(_line_index(starts, block.end) - anchor_line) <= 4:
                a_span = doc.locate(block.start, block.end)
                out.append(
                    Extraction(
                        key=FieldKey.CONSUMER_CARE_ADDRESS,
                        raw_text=block.text,
                        parsed=AddressDeclaration(pin=block.pin),
                        span=a_span,
                        confidence=_confidence(a_span, 0.2),
                    )
                )
    return out


# ------------------------------------------------------------------- manufacturer

# The inter-word gaps are `\s*`, not `\s+`: real OCR drops the space between words
# constantly ("MarketedBy:", "ManufacturedByDFMFoods"), and a label that needs the
# space simply is not found, which reads downstream as no manufacturer declared at all.
_MFR_LABEL = re.compile(
    r"(?P<role>Manufactured\s*(?:&\s*Packed\s*)?by|Mfd\.?\s*by|Mfg\.?\s*by|Packed\s*by|"
    r"Marketed\s*by|Mktd\.?\s*by|Imported\s*(?:&\s*Marketed\s*)?by|Manufacturer)"
    r"\s*[:\-.]?\s*(?P<name>[^\n]*)",
    re.I,
)

# A "name" that is actually a cross-reference — "see below", "scan the QR code to
# identify the manufacturing unit" — is not a manufacturer name.
_NOT_A_NAME = re.compile(
    r"\b(?:see\s*below|see\s*back|identif|scan\b|refer\b|first\s*letter|QR\s*code|"
    r"batch\s*no)\b",
    re.I,
)


# Bounded against digits rather than word boundaries, and tolerant of an internal
# separator. \b\d{6}\b missed both of the ways a PIN really reaches us: OCR losing the
# preceding space ("Nashik, Maharashtra422010") and India Post's own spaced form
# ("422 010"). Either way the address terminator was never found, so the address ran on
# and swallowed the net quantity and the price. The digit lookarounds still keep this
# out of a 14-digit FSSAI licence or an 11-digit toll-free number.
_PIN = re.compile(r"(?<!\d)(\d{3})[ -]?(\d{3})(?!\d)")


def _pin(text: str) -> str | None:
    match = _PIN.search(text)
    return match.group(1) + match.group(2) if match else None


# Words that tell a postal line apart from any other line that happens to carry digits.
_ADDRESS_HINT = re.compile(
    r"\b(?:road|rd|floor|flr|street|st|nagar|sector|phase|plot|gala|marg|lane|ln|"
    r"block|colony|layout|cross|industrial|estate|midc|hsi+dc|gidc|village|dist|"
    r"district|tehsil|taluka|ring|ashram|new\s*delhi)\b",
    re.I,
)


@dataclass(frozen=True)
class _AddressBlock:
    text: str
    pin: str
    start: int
    end: int


def _address_blocks(doc: OcrDocument) -> list[_AddressBlock]:
    """Every run of lines on the pack that ends in a PIN and reads like a postal
    address. A real declaration is often printed clearly on one panel and torn apart
    on the others, so an address is taken wherever one is legible — not only in the
    lines immediately beneath a heading."""
    lines = doc.text.split("\n")
    starts = _line_starts(doc.text)
    out: list[_AddressBlock] = []
    for i, line in enumerate(lines):
        pin = _pin(line)
        if pin is None:
            continue
        first = max(0, i - 4)
        run = [ln.strip() for ln in lines[first : i + 1] if ln.strip()]
        # Trim leading lines that carry nothing address-like — a stray caption the
        # reading order dropped in above the address should not become its first line.
        while len(run) > 1 and not (
            _ADDRESS_HINT.search(run[0]) or "," in run[0] or re.search(r"\d", run[0])
        ):
            run = run[1:]
        text = " ".join(run)
        if _ADDRESS_HINT.search(text) or text.count(",") >= 2:
            out.append(_AddressBlock(text, pin, starts[first], starts[i] + len(line)))
    return out


def _best_address_block(doc: OcrDocument, near: str | None = None) -> _AddressBlock | None:
    blocks = _address_blocks(doc)
    if not blocks:
        return None

    def score(b: _AddressBlock) -> tuple[int, int, float]:
        # Drop emails and URLs first: the company name recurs inside "care@dfmfoods.com"
        # and would otherwise make a noisy block outrank the clean postal one.
        prose = re.sub(r"\S*@\S*|https?://\S*|www\.\S*", " ", b.text.lower())
        squashed = re.sub(r"[^a-z]", "", prose)
        mentions = 1 if near and len(near) >= 4 and near.lower() in squashed else 0
        hits = len(_ADDRESS_HINT.findall(b.text)) + b.text.count(",")
        return (mentions, hits, doc.locate(b.start, b.end).confidence)

    return max(blocks, key=score)


# A contact person / department, tolerant of the OCR mangling "Consumer Service" gets.
_CONTACT_PERSON = re.compile(
    r"(?:Ser[vw]ice|Consumer|Customer|Care|Grievance|Complaint)\s*"
    r"(?:Manager|Officer|Cell|Executive|Dep(?:t|artment)?|Care)\.?",
    re.I,
)


def _resolve_mfr_name(doc: OcrDocument, match: re.Match[str]) -> tuple[str, int]:
    """The org name for one 'Manufactured by' heading, and where it ends in doc.text.

    Falls to the line below when the heading's own line carries nothing usable — the
    name is often set under the label rather than after it.
    """
    name = match.group("name").strip(" .,:-")
    name_end = match.end()
    if len(re.sub(r"[^A-Za-z]", "", name)) < 3:
        following = doc.lines_after(match.start(), 1)
        if following:
            name = following[0].strip(" .,:-")
            nl = doc.text.find("\n", doc.text.find("\n", match.start()) + 1)
            name_end = nl if nl != -1 else len(doc.text)
    return name, name_end


def _mfr_name_usable(name: str) -> bool:
    return len(re.sub(r"[^A-Za-z]", "", name)) >= 3 and not _NOT_A_NAME.search(name)


def extract_manufacturer(doc: OcrDocument) -> list[Extraction]:
    matches = list(_MFR_LABEL.finditer(doc.text))
    if not matches:
        return []

    # Choose among every "Manufactured/Marketed/Packed by" heading rather than taking
    # the first. An empty "Manufactured By:" that only points at a QR code must lose to
    # a "Marketed By:" that actually carries the name and a PIN-bearing address — which
    # is the legally sufficient declaration when the manufacturer address is not printed.
    resolved = [(m, *_resolve_mfr_name(doc, m)) for m in matches]

    def rank(item: tuple[re.Match[str], str, int]) -> tuple[bool, bool, bool, float, int]:
        m, name, name_end = item
        usable = _mfr_name_usable(name)
        block = " ".join(doc.lines_after(name_end - 1, 5))
        has_pin = _pin(block) is not None
        is_marketer = "market" in m.group("role").lower()
        conf = doc.locate(m.start(), name_end).confidence
        return (not (usable and has_pin), not usable, is_marketer, -conf, m.start())

    match, name, name_end = min(resolved, key=rank)

    out: list[Extraction] = []
    if name:
        span = doc.locate(match.start(), name_end)
        out.append(
            Extraction(
                key=FieldKey.MANUFACTURER_NAME,
                raw_text=name,
                parsed=NameDeclaration(text=name),
                span=span,
                confidence=_confidence(span),
            )
        )

    # Address: the run of lines after the name, up to and including the one with the PIN.
    following = doc.lines_after(name_end - 1, 5)
    address_lines: list[str] = []
    for line in following:
        address_lines.append(line.strip())
        if _pin(line):
            break
    address = " ".join(address_lines).strip()
    if address and (_pin(address) or len(address_lines) >= 2):
        end = name_end
        for _ in range(len(address_lines)):
            nxt = doc.text.find("\n", end + 1)
            if nxt == -1:
                break
            end = nxt
        span = doc.locate(name_end, end)
        out.append(
            Extraction(
                key=FieldKey.MANUFACTURER_ADDRESS,
                raw_text=address,
                parsed=AddressDeclaration(pin=_pin(address)),
                span=span,
                confidence=_confidence(span, 0.1),
            )
        )

    # The lines under the heading did not resolve to an address with a PIN, but the
    # same declaration may be printed legibly on another panel — the run reader put it
    # elsewhere in the flattened text. Take the clearest postal block on the pack.
    if not any(
        e.key == FieldKey.MANUFACTURER_ADDRESS and getattr(e.parsed, "pin", None) for e in out
    ):
        distinctive = next((w for w in re.findall(r"[A-Za-z]{4,}", name)), None)
        block = _best_address_block(doc, distinctive)
        if block is not None and _ADDRESS_HINT.search(block.text):
            span = doc.locate(block.start, block.end)
            out = [e for e in out if e.key != FieldKey.MANUFACTURER_ADDRESS]
            out.append(
                Extraction(
                    key=FieldKey.MANUFACTURER_ADDRESS,
                    raw_text=block.text,
                    parsed=AddressDeclaration(pin=block.pin),
                    span=span,
                    confidence=_confidence(span, 0.2),
                )
            )
    return out


# ---------------------------------------------------------------- country of origin

_ORIGIN = re.compile(
    r"(?:Country\s+of\s+Origin|Made\s+in|Product\s+of|Origin)\s*[:\-.]?\s*"
    r"(?P<country>[A-Za-z][A-Za-z .]{2,30})",
    re.I,
)


def extract_country_of_origin(doc: OcrDocument) -> Extraction | None:
    match = _ORIGIN.search(doc.text)
    if match is None:
        return None
    span = doc.locate(match.start(), match.end())
    return Extraction(
        key=FieldKey.COUNTRY_OF_ORIGIN,
        raw_text=match.group(0).strip(),
        parsed=OriginDeclaration(country=match.group("country").strip(" .") or None),
        span=span,
        confidence=_confidence(span),
    )


# ---------------------------------------------------------------- unit sale price

_USP = re.compile(
    rf"(?P<currency>{_CURRENCY})?\s*(?P<amount>{_AMOUNT})\s*(?:per|/)\s*"
    rf"(?P<unit>{_UNIT_ALTERNATION}|piece|pc|pcs)\b",
    re.I,
)
# The bare printed label. "USP" is only ever "unit sale price" on a retail pack, so it
# needs no value adjacent to be recognised as one — the value is stamped in the next
# column and often does not survive OCR (the "/g" here read as a stray "5").
_USP_LABEL_ONLY = re.compile(r"\b(?:U\.?\s?S\.?\s?P\.?|Unit\s*(?:Sale\s*)?Price)\b", re.I)


def extract_unit_sale_price(doc: OcrDocument) -> Extraction | None:
    for match in _USP.finditer(doc.text):
        unit = units.canonical(match.group("unit"))
        if unit is None:
            continue
        span = doc.locate(match.start(), match.end())
        return Extraction(
            key=FieldKey.UNIT_SALE_PRICE,
            raw_text=match.group(0).strip(),
            parsed=UnitPriceDeclaration(
                amount=_clean_amount(match.group("amount")), per_unit=unit
            ),
            span=span,
            confidence=_confidence(span),
        )

    # A unit-sale-price label is printed but its stamped value did not read as a
    # "<amount> per <unit>" anywhere. Present but unreadable — hand it to an officer
    # rather than reporting no unit price on a pack that plainly prints one.
    if label := _USP_LABEL_ONLY.search(doc.text):
        return _label_only_stub(
            doc, label, FieldKey.UNIT_SALE_PRICE, UnitPriceDeclaration()
        )
    return None


# ------------------------------------------------------------------- supporting

# The lookbehind matters: without it "Lot" matches inside "Plot 14, MIDC Ambad" and
# the batch number is read as the street number.
_BATCH = re.compile(
    r"(?<![A-Za-z])(?:Batch|Lot|B\.?\s?No)\.?\s*(?:No\.?)?\s*[:\-.]?\s*"
    r"(?P<batch>[A-Z0-9][A-Z0-9\-/]{1,15})",
    re.I,
)
_FSSAI = re.compile(r"(?:FSSAI|Lic(?:ence|ense)?\.?\s*No\.?)[^\d]{0,12}(?P<num>\d{14})", re.I)


def _simple(doc: OcrDocument, pattern: re.Pattern[str], key: str, group: str) -> Extraction | None:
    match = pattern.search(doc.text)
    if match is None:
        return None
    span = doc.locate(match.start(), match.end())
    return Extraction(
        key=key,
        raw_text=match.group(group).strip(),
        parsed=NameDeclaration(text=match.group(group).strip()),
        span=span,
        confidence=_confidence(span),
    )


# ------------------------------------------------------------------- common name

_NOISE = re.compile(
    r"(?:mrp|net|qty|quantity|mfg|mfd|packed|marketed|manufactured|batch|lot|fssai|"
    r"consumer|customer|care|www|http|@|₹|rs\.|inclusive|tax|origin|best before|"
    r"expiry|ingredients|nutrition|per\s+\d|store|keep)",
    re.I,
)
# Rule 6(1)(b) wants what the thing *is*, and packs say so in ordinary words.
_GENERIC_HINT = re.compile(
    r"\b(?:biscuit|cookie|namkeen|chana|dal|atta|maida|rice|flour|oil|ghee|masala|"
    r"powder|spice|tea|coffee|juice|beverage|drink|water|milk|curd|paneer|butter|"
    r"cheese|chips|wafer|noodle|pasta|sauce|ketchup|pickle|jam|honey|sugar|salt|"
    r"soap|shampoo|detergent|cream|lotion|paste|brush|sanitiser|sanitizer|"
    r"chocolate|candy|snack|mixture|bhujia|papad|poha|suji|besan|nuts|almond|cashew)\w*",
    re.I,
)


def extract_common_name(doc: OcrDocument) -> Extraction | None:
    """Prefer an explicit generic word; fall back to the most prominent clean line."""
    if hint := _GENERIC_HINT.search(doc.text):
        start = doc.text.rfind("\n", 0, hint.start()) + 1
        end = doc.text.find("\n", hint.end())
        end = end if end != -1 else len(doc.text)
        line = doc.text[start:end].strip()
        if len(line) <= 60 and not _NOISE.search(line):
            span = doc.locate(start, end)
            return Extraction(
                key=FieldKey.COMMON_NAME,
                raw_text=line,
                parsed=NameDeclaration(text=line),
                span=span,
                confidence=_confidence(span, 0.05),
            )

    # Fallback: the tallest block that reads like a name rather than a declaration.
    candidates = [
        b
        for b in doc.blocks
        if 3 <= len(b.text.strip()) <= 40
        and not _NOISE.search(b.text)
        and any(c.isalpha() for c in b.text)
    ]
    if not candidates:
        return None
    block = max(candidates, key=lambda b: b.height_px)
    index = doc.text.find(block.text)
    span = doc.locate(index, index + len(block.text)) if index >= 0 else Span(0, 0, [block])
    return Extraction(
        key=FieldKey.COMMON_NAME,
        raw_text=block.text.strip(),
        parsed=NameDeclaration(text=block.text.strip()),
        # A guess from prominence is weak evidence; say so rather than assert it.
        span=span,
        confidence=_confidence(span, 0.45),
    )


# --------------------------------------------------------------------------- run

SINGLE: dict[str, Callable[[OcrDocument], Extraction | None]] = {
    FieldKey.MRP: extract_mrp,
    FieldKey.NET_QUANTITY: extract_net_quantity,
    FieldKey.MFG_DATE: extract_mfg_date,
    FieldKey.COUNTRY_OF_ORIGIN: extract_country_of_origin,
    FieldKey.UNIT_SALE_PRICE: extract_unit_sale_price,
    FieldKey.COMMON_NAME: extract_common_name,
    FieldKey.BATCH_NUMBER: lambda d: _simple(d, _BATCH, FieldKey.BATCH_NUMBER, "batch"),
    FieldKey.FSSAI_NUMBER: lambda d: _simple(d, _FSSAI, FieldKey.FSSAI_NUMBER, "num"),
}

MULTI: tuple[Callable[[OcrDocument], list[Extraction]], ...] = (
    extract_consumer_care,
    extract_manufacturer,
)


def extract_all(doc: OcrDocument) -> dict[str, Extraction]:
    """Every declaration this extractor can find, keyed by FieldKey."""
    found: dict[str, Extraction] = {}
    for key, fn in SINGLE.items():
        try:
            if (result := fn(doc)) is not None:
                found[key] = result
        except Exception:  # one bad pattern must not cost us the other declarations
            continue
    for multi in MULTI:
        try:
            for result in multi(doc):
                found.setdefault(result.key, result)
        except Exception:
            continue
    return found
