"""Extraction tests written against how Indian packs are actually printed."""

from __future__ import annotations

import pytest

from app.models.enums import FieldKey
from app.pipeline.fields import extract_all
from app.pipeline.ocr import OcrBlock, OcrDocument


def doc_from(text: str, *, conf: float = 0.95, line_height: float = 20.0) -> OcrDocument:
    """Build a document from plain lines, laid out as if read off one panel."""
    blocks = []
    for row, line in enumerate(ln for ln in text.strip().split("\n") if ln.strip()):
        blocks.append(
            OcrBlock(
                text=line.strip(),
                polygon=[
                    [10.0, 10.0 + row * (line_height + 6)],
                    [10.0 + len(line) * 9, 10.0 + row * (line_height + 6)],
                    [10.0 + len(line) * 9, 10.0 + row * (line_height + 6) + line_height],
                    [10.0, 10.0 + row * (line_height + 6) + line_height],
                ],
                confidence=conf,
                image_id="img1",
            )
        )
    return OcrDocument.build(blocks)


BACK_PANEL = """
Roasted Chana Masala
Manufactured by: Sunrise Foods Private Limited
Plot 14, MIDC Ambad
Nashik, Maharashtra 422010
Net Qty: 200 g
MRP Rs. 45.00
(inclusive of all taxes)
Mfd. 03/2026
Batch No: RC2603A
FSSAI Lic No. 11522004000123
Consumer Care: care@sunrisefoods.in
Toll free 1800 200 1234
"""


@pytest.fixture
def back_panel():
    return extract_all(doc_from(BACK_PANEL))


# --------------------------------------------------------------------- happy path


def test_reads_a_complete_back_panel(back_panel):
    expected = {
        FieldKey.MANUFACTURER_NAME,
        FieldKey.MANUFACTURER_ADDRESS,
        FieldKey.COMMON_NAME,
        FieldKey.NET_QUANTITY,
        FieldKey.MRP,
        FieldKey.MFG_DATE,
        FieldKey.CONSUMER_CARE_EMAIL,
        FieldKey.CONSUMER_CARE_PHONE,
        FieldKey.BATCH_NUMBER,
        FieldKey.FSSAI_NUMBER,
    }
    assert expected <= set(back_panel)


def test_mrp_amount_and_tax_phrase_across_two_lines(back_panel):
    mrp = back_panel[FieldKey.MRP]
    assert mrp.parsed.amount == 45.0
    assert mrp.parsed.inclusive_of_taxes is True
    assert mrp.parsed.all_amounts == (45.0,)


def test_net_quantity_value_unit_and_basis(back_panel):
    net = back_panel[FieldKey.NET_QUANTITY]
    assert net.parsed.value == 200.0
    assert net.parsed.unit == "g"
    assert net.parsed.basis == "WEIGHT"


def test_manufacturer_name_excludes_the_label(back_panel):
    assert back_panel[FieldKey.MANUFACTURER_NAME].raw_text == "Sunrise Foods Private Limited"


def test_manufacturer_address_runs_to_the_pin_code(back_panel):
    address = back_panel[FieldKey.MANUFACTURER_ADDRESS]
    assert address.parsed.pin == "422010"
    assert "MIDC Ambad" in address.raw_text


def test_manufacture_date_parses_to_month_and_year(back_panel):
    date = back_panel[FieldKey.MFG_DATE].parsed
    assert (date.month, date.year) == (3, 2026)


def test_contact_details(back_panel):
    assert back_panel[FieldKey.CONSUMER_CARE_EMAIL].raw_text == "care@sunrisefoods.in"
    assert back_panel[FieldKey.CONSUMER_CARE_PHONE].parsed.digits == "18002001234"


def test_common_name_prefers_the_generic_word(back_panel):
    assert "Chana" in back_panel[FieldKey.COMMON_NAME].raw_text


def test_every_extraction_points_back_at_pixels(back_panel):
    for key, extraction in back_panel.items():
        assert extraction.bbox is not None, f"{key} has no bounding box"
        assert extraction.image_id == "img1"
        x, y, w, h = extraction.bbox
        assert w > 0 and h > 0


# --------------------------------------------------------------------- MRP variants


@pytest.mark.parametrize(
    ("line", "amount"),
    [
        ("MRP ₹45.00 incl. of all taxes", 45.0),
        ("M.R.P. Rs 1,250.50 inclusive of all taxes", 1250.50),
        ("Maximum Retail Price: INR 99 inclusive of all taxes", 99.0),
        ("Retail Sale Price Rs.5 (Incl. of all taxes)", 5.0),
        ("MRP: 45", 45.0),
        # Printed-form label: the static "MRP (Rs) incl. of all taxes" heading and the
        # stamped figure land on one row, with the figure past the rider and carrying
        # no rupee mark of its own.
        ("MRP (Rs) incl. of all taxes 229.00", 229.0),
        ("M.R.P inclusive of all taxes 45.00", 45.0),
    ],
)
def test_mrp_forms(line, amount):
    found = extract_all(doc_from(line))
    assert found[FieldKey.MRP].parsed.amount == amount


def test_mrp_value_past_an_inline_tax_rider():
    """The amount is not adjacent to the MRP token and has no mark of its own; the
    rupee mark is still recoverable from "(Rs)" earlier on the same row, and the row
    says it is tax-inclusive."""
    mrp = extract_all(doc_from("MRP (Rs) incl. of all taxes 229.00"))[FieldKey.MRP]
    assert mrp.parsed.amount == 229.0
    assert mrp.parsed.currency_mark is not None
    assert mrp.parsed.inclusive_of_taxes is True


def test_manufacturer_label_is_read_regardless_of_case():
    """_MFR_LABEL is case-insensitive: an ALL-CAPS "MANUFACTURED BY" heading is still
    a manufacturer declaration, not a missing one."""
    found = extract_all(
        doc_from(
            "ROASTED CHANA MASALA\n"
            "MANUFACTURED BY: SUNRISE FOODS PRIVATE LIMITED\n"
            "PLOT 14, MIDC AMBAD, NASHIK, MAHARASHTRA 422010\n"
        )
    )
    assert FieldKey.MANUFACTURER_NAME in found
    assert "SUNRISE FOODS" in found[FieldKey.MANUFACTURER_NAME].raw_text.upper()


def test_dual_mrp_collects_both_prices():
    found = extract_all(doc_from("MRP Rs. 45.00 inclusive of all taxes\nMRP Rs. 50.00"))
    assert found[FieldKey.MRP].parsed.all_amounts == (45.0, 50.0)


def test_missing_tax_phrase_is_reported_as_absent():
    found = extract_all(doc_from("MRP Rs. 45.00"))
    assert found[FieldKey.MRP].parsed.inclusive_of_taxes is False


def test_thousands_separator_is_handled():
    found = extract_all(doc_from("MRP Rs. 12,499.00 inclusive of all taxes"))
    assert found[FieldKey.MRP].parsed.amount == 12499.0


# ------------------------------------------------------------- net quantity variants


@pytest.mark.parametrize(
    ("line", "value", "unit"),
    [
        ("Net Qty 500 g", 500.0, "g"),
        ("Net Weight: 1 kg", 1.0, "kg"),
        ("Net Vol. 250 ml", 250.0, "ml"),
        ("Net Content 1.5 ltr", 1.5, "l"),
        ("Net Quantity : 10 pcs", 10.0, "pcs"),
        ("Quantity 100 gms", 100.0, "g"),
    ],
)
def test_net_quantity_forms(line, value, unit):
    net = extract_all(doc_from(line))[FieldKey.NET_QUANTITY]
    assert (net.parsed.value, net.parsed.unit) == (value, unit)


def test_unlabelled_quantity_is_found_but_less_certain():
    labelled = extract_all(doc_from("Net Qty 200 g"))[FieldKey.NET_QUANTITY]
    bare = extract_all(doc_from("200 g"))[FieldKey.NET_QUANTITY]
    assert bare.parsed.value == 200.0
    assert bare.confidence < labelled.confidence


# ------------------------------------------------------------------- date variants


@pytest.mark.parametrize(
    ("line", "month", "year"),
    [
        ("Mfd. 03/2026", 3, 2026),
        ("MFG: 12-25", 12, 2025),
        ("Packed on 07.2026", 7, 2026),
        ("Date of Manufacture: MAR 2026", 3, 2026),
        ("PKD 01/26", 1, 2026),
    ],
)
def test_manufacture_date_forms(line, month, year):
    parsed = extract_all(doc_from(line))[FieldKey.MFG_DATE].parsed
    assert (parsed.month, parsed.year) == (month, year)


# ------------------------------------------------------------------ consumer care


def test_consumer_care_block_with_address():
    text = """
    Consumer Care Cell
    Sunrise Foods Pvt Ltd, Plot 14
    Nashik 422010
    care@sunrisefoods.in
    1800 200 1234
    """
    found = extract_all(doc_from(text))
    assert FieldKey.CONSUMER_CARE_NAME in found
    assert found[FieldKey.CONSUMER_CARE_ADDRESS].parsed.pin == "422010"
    assert found[FieldKey.CONSUMER_CARE_EMAIL].raw_text == "care@sunrisefoods.in"


@pytest.mark.parametrize(
    "phone",
    ["1800 200 1234", "1800-102-1234", "+91 98765 43210", "022 27564321", "9876543210"],
)
def test_phone_forms(phone):
    found = extract_all(doc_from(f"Customer Care\n{phone}"))
    assert FieldKey.CONSUMER_CARE_PHONE in found


def test_a_pin_code_is_not_mistaken_for_a_phone_number():
    found = extract_all(doc_from("Consumer Care\nNashik 422010"))
    assert FieldKey.CONSUMER_CARE_PHONE not in found


# --------------------------------------------------------------------- other fields


def test_marketer_is_not_preferred_over_the_manufacturer():
    text = """
    Marketed by: Bright Retail LLP
    Gurugram 122001
    Manufactured by: Sunrise Foods Private Limited
    Nashik 422010
    """
    found = extract_all(doc_from(text))
    assert found[FieldKey.MANUFACTURER_NAME].raw_text == "Sunrise Foods Private Limited"


@pytest.mark.parametrize(
    ("line", "country"),
    [
        ("Country of Origin: Vietnam", "Vietnam"),
        ("Made in China", "China"),
        ("Product of Sri Lanka", "Sri Lanka"),
    ],
)
def test_country_of_origin_forms(line, country):
    found = extract_all(doc_from(line))
    assert found[FieldKey.COUNTRY_OF_ORIGIN].parsed.country == country


@pytest.mark.parametrize(
    ("line", "amount", "unit"),
    [("₹0.23 per g", 0.23, "g"), ("Rs. 450 per kg", 450.0, "kg"), ("₹2.50/ml", 2.50, "ml")],
)
def test_unit_sale_price_forms(line, amount, unit):
    usp = extract_all(doc_from(line))[FieldKey.UNIT_SALE_PRICE]
    assert (usp.parsed.amount, usp.parsed.per_unit) == (amount, unit)


def test_batch_and_licence_numbers():
    found = extract_all(doc_from("Batch No: RC2603A\nFSSAI Lic No. 11522004000123"))
    assert found[FieldKey.BATCH_NUMBER].raw_text == "RC2603A"
    assert found[FieldKey.FSSAI_NUMBER].raw_text == "11522004000123"


# ------------------------------------------------------------------- failure modes


def test_a_blank_panel_yields_nothing_rather_than_guesses():
    assert extract_all(doc_from("   \n  \n ")) == {}


def test_low_ocr_confidence_is_carried_through_to_the_field():
    found = extract_all(doc_from("Net Qty 200 g\nMRP Rs. 45.00", conf=0.30))
    assert all(e.confidence <= 0.31 for e in found.values())


def test_extraction_survives_garbled_text():
    found = extract_all(doc_from("###\n@@@ ???\nNet Qty 200 g\n\x00\x01"))
    assert found[FieldKey.NET_QUANTITY].parsed.value == 200.0


def test_common_name_falls_back_to_prominence_with_low_confidence():
    found = extract_all(doc_from("ZORVEX\nNet Qty 200 g\nMRP Rs. 45.00"))
    name = found.get(FieldKey.COMMON_NAME)
    assert name is not None and name.confidence < 0.6


# --------------------------------------------- OCR spacing loss (real detector output)


@pytest.mark.parametrize(
    "address_line",
    [
        "Nashik, Maharashtra 422010",
        "Nashik,Maharashtra422010",   # OCR drops the spaces in dense address blocks
        "Nashik Maharashtra-422010",
        "NASHIK MH422010",
        "Nashik, MH - 422 010",
    ],
)
def test_a_pin_code_is_found_even_when_ocr_loses_the_spaces(address_line):
    text = f"""
    Manufactured by: Sunrise Foods Private Limited
    Plot 14, MIDC Ambad
    {address_line}
    Net Qty: 200 g
    MRP Rs. 45.00
    """
    found = extract_all(doc_from(text))
    address = found[FieldKey.MANUFACTURER_ADDRESS]
    assert "Net Qty" not in address.raw_text, "address ran on past its PIN code"
    assert "MRP" not in address.raw_text


def test_the_address_stops_at_the_pin_and_does_not_swallow_the_price():
    """The runaway case: without a PIN terminator the address absorbed five lines,
    took the net quantity and both prices with it, and reported no PIN at all."""
    text = """
    Manufactured by: Sunrise Foods Private Limited
    Plot 14, MIDC Ambad
    Nashik,Maharashtra422010
    Net Qty: 200 g
    MRP Rs.45.00
    """
    address = extract_all(doc_from(text))[FieldKey.MANUFACTURER_ADDRESS]
    assert address.parsed.pin == "422010"
    assert "45.00" not in address.raw_text


@pytest.mark.parametrize(
    "line",
    ["FSSAI Lic No. 11522004000123", "Toll free 18002001234", "Batch 1234567890"],
)
def test_long_digit_runs_are_not_mistaken_for_a_pin_code(line):
    from app.pipeline.fields import _pin

    assert _pin(line) is None


# ----------------------------------------- tax rider separated from the price


def test_the_tax_rider_is_found_on_the_line_below():
    found = extract_all(doc_from("MRP Rs. 45.00\n(inclusive of all taxes)"))
    assert found[FieldKey.MRP].parsed.inclusive_of_taxes is True


@pytest.mark.parametrize(
    "between",
    [
        "MRP Rs. 50.00",          # a struck-through or dual price
        "Batch No: RC2603A",
        "Mfd. 03/2026",
        "Net Qty: 200 g\nBatch No: RC2603A",
    ],
)
def test_the_tax_rider_is_found_past_intervening_lines(between):
    """Reporting a compliant pack as declaring no tax inclusion, because the rider was
    one line further down than the extractor looked."""
    found = extract_all(doc_from(f"MRP Rs. 45.00\n{between}\n(inclusive of all taxes)"))
    assert found[FieldKey.MRP].parsed.inclusive_of_taxes is True


def test_a_pack_genuinely_without_the_tax_rider_is_still_reported_as_such():
    """The lookahead must not manufacture compliance where there is none."""
    found = extract_all(doc_from("MRP Rs. 45.00\nBatch No: RC2603A\nMfd. 03/2026\nNet Qty 200 g"))
    assert found[FieldKey.MRP].parsed.inclusive_of_taxes is False


def test_the_tax_rider_lookahead_does_not_reach_across_the_whole_label():
    far = "\n".join(
        ["MRP Rs. 45.00", *[f"Line {i}" for i in range(8)], "(inclusive of all taxes)"]
    )
    assert extract_all(doc_from(far))[FieldKey.MRP].parsed.inclusive_of_taxes is False


# ------------------------------- currency marking, incl. when OCR glues the tokens


@pytest.mark.parametrize(
    ("printed", "mark"),
    [
        ("MRP Rs. 45.00", "Rs."),
        ("MRPRs.45.00", "Rs."),        # OCR drops the space between label and marking
        ("MRP ₹45.00", "₹"),
        ("MRP₹45.00", "₹"),
        ("MRP INR 45.00", "INR"),
        ("M.R.P.Rs45.00", "Rs"),
    ],
)
def test_the_rupee_marking_is_captured_however_it_is_spaced(printed, mark):
    found = extract_all(doc_from(printed))[FieldKey.MRP]
    assert found.parsed.currency_mark is not None
    assert mark.rstrip(".") in found.parsed.currency_mark


def test_a_price_with_no_rupee_marking_records_none():
    """The marking must reflect what was printed, not be assumed."""
    found = extract_all(doc_from("MRP 45.00 inclusive of all taxes"))[FieldKey.MRP]
    assert found.parsed.currency_mark is None
