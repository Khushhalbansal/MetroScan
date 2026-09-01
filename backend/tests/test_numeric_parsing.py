"""Numbers read off a pack, across the formats Indian labels actually use.

The class of bug these cover: a value that parses to something plausible but wrong.
A price truncated from ₹45000 to ₹450 does not crash and does not look like an error
— it flows into the MRP shown on the report, the dual-price comparison and the unit
price cross-check, all of which then reason confidently about a number that was never
on the package.
"""

from __future__ import annotations

import pytest
from test_field_extraction import doc_from

from app.models.enums import FieldKey
from app.pipeline.fields import extract_all
from app.rules.units import Basis


def amount_of(text: str) -> float | None:
    found = extract_all(doc_from(text)).get(FieldKey.MRP)
    return found.parsed.amount if found else None


# ------------------------------------------------------- ungrouped digit runs


@pytest.mark.parametrize(
    ("printed", "expected"),
    [
        ("MRP Rs. 45", 45.0),
        ("MRP Rs. 250", 250.0),
        ("MRP Rs. 1234", 1234.0),      # four digits, no separator
        ("MRP Rs. 9999", 9999.0),
        ("MRP Rs. 45000", 45000.0),    # was read as 450 — a hundredfold error
        ("MRP Rs. 125000", 125000.0),
        ("MRP Rs. 1099.50", 1099.50),
        ("MRP Rs. 19999.00", 19999.00),
    ],
)
def test_prices_without_digit_grouping(printed, expected):
    assert amount_of(printed) == expected


# ---------------------------------------------------- Indian digit grouping


@pytest.mark.parametrize(
    ("printed", "expected"),
    [
        ("MRP Rs. 12,499", 12499.0),
        ("MRP Rs. 1,25,000", 125000.0),      # lakh grouping
        ("MRP Rs. 12,50,000", 1250000.0),
        ("MRP Rs. 1,250.50", 1250.50),
        ("MRP Rs. 99,999.99", 99999.99),
    ],
)
def test_prices_with_indian_digit_grouping(printed, expected):
    assert amount_of(printed) == expected


def test_grouped_and_ungrouped_forms_of_one_price_agree():
    """The same money, printed two ways, must parse to the same number."""
    assert amount_of("MRP Rs. 45,000") == amount_of("MRP Rs. 45000") == 45000.0


def test_a_large_price_is_not_silently_truncated():
    """Guards the shape of the bug rather than one instance of it."""
    for digits in range(1, 8):
        printed = "9" * digits
        assert amount_of(f"MRP Rs. {printed}") == float(printed), (
            f"{digits}-digit price was not read whole"
        )


def test_a_truncated_price_would_break_the_dual_price_check():
    """Why it matters: two different prices must not collapse into one value."""
    found = extract_all(doc_from("MRP Rs. 45000\nMRP Rs. 45900"))[FieldKey.MRP]
    assert found.parsed.all_amounts == (45000.0, 45900.0)


# ------------------------------------------------------------ net quantity


@pytest.mark.parametrize(
    ("printed", "value", "unit"),
    [
        ("Net Qty 1000 g", 1000.0, "g"),
        ("Net Qty 1500 ml", 1500.0, "ml"),
        ("Net Qty 2500 g", 2500.0, "g"),
        ("Net Qty 1,000 g", 1000.0, "g"),
        ("Net Qty 12.5 kg", 12.5, "kg"),
    ],
)
def test_large_net_quantities_are_read_whole(printed, value, unit):
    net = extract_all(doc_from(printed))[FieldKey.NET_QUANTITY]
    assert (net.parsed.value, net.parsed.unit) == (value, unit)


# ------------------------------------------------------- unit alternation


def test_unit_alternation_is_ordered_longest_first():
    """Alternation takes the first match, so a short unit must never precede a longer
    one it prefixes — otherwise "g" would win against "gms"."""
    from app.pipeline.fields import _UNIT_ALTERNATION

    alts = _UNIT_ALTERNATION.split("|")
    lengths = [len(a.replace("\\", "")) for a in alts]
    assert lengths == sorted(lengths, reverse=True), "unit alternation lost its ordering"


def test_unit_alternation_has_no_duplicates():
    from app.pipeline.fields import _UNIT_ALTERNATION

    alts = _UNIT_ALTERNATION.split("|")
    dupes = {a for a in alts if alts.count(a) > 1}
    assert dupes == set(), f"duplicated alternatives: {dupes}"


@pytest.mark.parametrize(
    ("printed", "unit"),
    [
        ("Net Qty 200 gms", "g"),
        ("Net Qty 200 gm", "g"),
        ("Net Qty 2 kgs", "kg"),
        ("Net Qty 500 mls", "ml"),
        ("Net Qty 1 litre", "l"),
        ("Net Qty 5 metres", "m"),
        ("Net Qty 10 pieces", "pcs"),
    ],
)
def test_longer_unit_spellings_win_over_their_prefixes(printed, unit):
    net = extract_all(doc_from(printed))[FieldKey.NET_QUANTITY]
    assert net.parsed.unit == unit


@pytest.mark.parametrize("printed", ["Net Qty 50 cm2", "Net Qty 50 cm²"])
def test_superscript_area_units_are_recognised(printed):
    net = extract_all(doc_from(printed))[FieldKey.NET_QUANTITY]
    assert net.parsed.unit == "cm2"
    assert net.parsed.basis == Basis.AREA
