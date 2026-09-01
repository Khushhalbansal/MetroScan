"""How OCR boxes become searchable text.

The class of bug these cover: a declaration torn in half by the layout step. Detectors
routinely split one printed line into several boxes — a price and its "(inclusive of
all taxes)" rider, a label and its value, an address and its PIN. If the document
joins those with a line break, every pattern that reads a line at a time sees only a
fragment, and a compliant pack picks up a violation it does not have.
"""

from __future__ import annotations

import pytest

from app.models.enums import FieldKey
from app.pipeline.fields import extract_all
from app.pipeline.ocr import OcrBlock, OcrDocument


def block(text: str, x: float, y: float, *, h: float = 20.0, image: str = "img1",
          conf: float = 0.95) -> OcrBlock:
    w = len(text) * 9
    return OcrBlock(
        text=text,
        polygon=[[x, y], [x + w, y], [x + w, y + h], [x, y + h]],
        confidence=conf,
        image_id=image,
    )


# ------------------------------------------------------ one line, several boxes


def test_boxes_sharing_a_line_are_joined_with_a_space():
    doc = OcrDocument.build([block("Net Qty:", 10, 10), block("200 g", 120, 10)])
    assert doc.text == "Net Qty: 200 g"


def test_boxes_on_different_lines_are_joined_with_a_newline():
    doc = OcrDocument.build([block("MRP Rs. 45.00", 10, 10), block("Net Qty 200 g", 10, 60)])
    assert doc.text == "MRP Rs. 45.00\nNet Qty 200 g"


def test_a_split_line_is_reassembled_in_reading_order():
    """Boxes arrive in detector order, not reading order."""
    doc = OcrDocument.build(
        [block("taxes)", 400, 10), block("MRP Rs.45.00 (inclusive of all", 10, 10)]
    )
    assert doc.text == "MRP Rs.45.00 (inclusive of all taxes)"


def test_the_tax_phrase_survives_being_split_across_boxes():
    """A compliant pack must not pick up an MRP violation from OCR box boundaries."""
    doc = OcrDocument.build(
        [block("MRP Rs.45.00 (inclusive of all", 10, 10), block("taxes)", 400, 10)]
    )
    mrp = extract_all(doc)[FieldKey.MRP]
    assert mrp.parsed.inclusive_of_taxes is True


def test_a_split_declaration_keeps_evidence_covering_both_boxes():
    doc = OcrDocument.build(
        [block("MRP Rs.45.00 (inclusive of all", 10, 10), block("taxes)", 400, 10)]
    )
    x, _, w, _ = extract_all(doc)[FieldKey.MRP].bbox
    assert x == pytest.approx(10)
    assert x + w > 400, "evidence box does not reach the second half of the line"


def test_a_label_split_from_its_value_still_reads():
    doc = OcrDocument.build([block("Net Qty:", 10, 10), block("200 g", 120, 10)])
    net = extract_all(doc)[FieldKey.NET_QUANTITY]
    assert (net.parsed.value, net.parsed.unit) == (200.0, "g")


def test_manufacturer_split_from_its_label_still_reads():
    doc = OcrDocument.build(
        [block("Manufactured by:", 10, 10), block("Sunrise Foods Private Limited", 160, 10)]
    )
    found = extract_all(doc)
    assert found[FieldKey.MANUFACTURER_NAME].raw_text == "Sunrise Foods Private Limited"


# ----------------------------------------------------------- line-level helpers


def test_line_containing_returns_the_whole_reassembled_line():
    doc = OcrDocument.build(
        [block("MRP Rs. 45.00", 10, 10), block("(inclusive of all taxes)", 200, 10),
         block("Net Qty 200 g", 10, 60)]
    )
    index = doc.text.find("MRP")
    assert doc.line_containing(index) == "MRP Rs. 45.00 (inclusive of all taxes)"


def test_lines_after_skips_to_the_next_physical_line():
    doc = OcrDocument.build(
        [block("Consumer Care", 10, 10), block("Cell", 140, 10),
         block("Nashik 422010", 10, 60)]
    )
    assert doc.lines_after(0, 2) == ["Nashik 422010"]


# ------------------------------------------------------------------- ordering


def test_lines_are_ordered_top_to_bottom():
    doc = OcrDocument.build(
        [block("third", 10, 110), block("first", 10, 10), block("second", 10, 60)]
    )
    assert doc.text.split("\n") == ["first", "second", "third"]


def test_blocks_within_a_line_are_ordered_left_to_right():
    doc = OcrDocument.build([block("c", 300, 10), block("a", 10, 10), block("b", 150, 10)])
    assert doc.text == "a b c"


def test_pages_are_kept_separate():
    doc = OcrDocument.build(
        [block("back", 10, 10, image="back"), block("front", 10, 10, image="front")]
    )
    assert "\n" in doc.text, "declarations from two panels ran together on one line"


def test_locate_resolves_a_span_to_its_own_image():
    doc = OcrDocument.build(
        [block("Brand", 10, 10, image="front"), block("MRP Rs. 45.00", 10, 10, image="back")]
    )
    index = doc.text.find("MRP")
    assert doc.locate(index, index + 13).image_id == "back"


def test_locate_ignores_the_separators_between_blocks():
    doc = OcrDocument.build([block("Net Qty:", 10, 10), block("200 g", 120, 10)])
    span = doc.locate(0, len(doc.text))
    assert [b.text for b in span.blocks] == ["Net Qty:", "200 g"]


def test_locate_out_of_range_is_empty_rather_than_an_error():
    doc = OcrDocument.build([block("Net Qty 200 g", 10, 10)])
    assert doc.locate(500, 900).blocks == []
    assert doc.locate(-10, 0).blocks == []


# --------------------------------------------------------- malformed geometry


def test_rotated_text_is_measured_along_its_own_axis():
    """A vertical declaration is 20 px tall, not 190."""
    tall = OcrBlock("MRP Rs. 45.00", [[10, 10], [30, 10], [30, 200], [10, 200]], 0.9, "img1")
    assert tall.height_px == pytest.approx(20)
    assert tall.width_px == pytest.approx(190)


@pytest.mark.parametrize(
    "polygon",
    [
        [[0, 0], [10, 0], [10, 10]],          # three corners
        [[0, 0], [10, 0]],                     # two corners
        [[0, 0]],                              # one corner
        [],                                    # none at all
        [[0, 0], [10, 0], [10, 10], [0]],      # a truncated corner
    ],
)
def test_a_malformed_polygon_does_not_crash_the_scan(polygon):
    """Blocks rehydrated from stored JSON are not guaranteed to be quadrilaterals, and
    OcrDocument.build reads this geometry outside the runner's per-image guard."""
    block_ = OcrBlock("MRP Rs. 45.00", polygon, 0.9, "img1")
    assert block_.height_px >= 0
    assert block_.width_px >= 0
    doc = OcrDocument.build([block_])
    assert extract_all(doc)[FieldKey.MRP].parsed.amount == 45.0


def test_a_degenerate_polygon_measures_nothing_rather_than_guessing():
    flat = OcrBlock("x", [[5, 5], [5, 5], [5, 5], [5, 5]], 0.9, "img1")
    assert flat.height_px == 0
    assert flat.width_px == 0


def test_blank_detections_do_not_open_empty_lines():
    doc = OcrDocument.build([block("   ", 10, 10), block("MRP Rs. 45.00", 10, 60)])
    assert doc.text == "MRP Rs. 45.00"


def test_the_same_price_on_two_panels_is_not_a_dual_price():
    """Front and back both carry the MRP; that is one price, not two."""
    doc = OcrDocument.build(
        [block("MRP Rs. 45.00 inclusive of all taxes", 10, 10, image="front"),
         block("MRP Rs. 45.00 inclusive of all taxes", 10, 10, image="back")]
    )
    assert extract_all(doc)[FieldKey.MRP].parsed.all_amounts == (45.0,)


def test_an_empty_document_is_safe():
    doc = OcrDocument.build([])
    assert doc.text == ""
    assert doc.blocks == []
    assert doc.mean_confidence == 0.0
    assert extract_all(doc) == {}
