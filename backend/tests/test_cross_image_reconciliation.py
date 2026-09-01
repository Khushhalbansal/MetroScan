"""Evidence for a field is merged across every image before it is judged.

A declaration is commonly captured on more than one of a scan's photographs — sharp on
one, smeared or cropped on another. The extractor must give the field the benefit of
the clearest photograph it appears in, not simply take whichever image sorted first.
It must still never invent a value: a field absent everywhere stays absent.
"""

from __future__ import annotations

from app.models.enums import FieldKey
from app.pipeline.fields import extract_all
from app.pipeline.ocr import OcrBlock, OcrDocument


def block(text: str, y: float, *, image: str, conf: float) -> OcrBlock:
    w = len(text) * 9
    return OcrBlock(
        text=text,
        polygon=[[10.0, y], [10.0 + w, y], [10.0 + w, y + 20.0], [10.0, y + 20.0]],
        confidence=conf,
        image_id=image,
    )


def test_the_clear_copy_in_the_second_image_wins_over_a_blurred_first_one():
    """img_a sorts first and carries a smeared manufacturer; img_b has it clean; img_c
    is an unrelated nutrition panel. The finding must come from img_b."""
    doc = OcrDocument.build(
        [
            block("Manufactured by: Snx", 10, image="img_a", conf=0.31),
            block("addr on base of pack", 40, image="img_a", conf=0.31),
            block("Manufactured by: Sunrise Foods Private Limited", 10, image="img_b", conf=0.97),
            block("Plot 14, MIDC Ambad", 40, image="img_b", conf=0.96),
            block("Nashik, Maharashtra 422010", 70, image="img_b", conf=0.96),
            block("Nutritional Information per 100 g", 10, image="img_c", conf=0.9),
            block("Energy 402 kcal", 40, image="img_c", conf=0.9),
        ]
    )
    found = extract_all(doc)

    name = found[FieldKey.MANUFACTURER_NAME]
    assert name.raw_text == "Sunrise Foods Private Limited"
    assert name.image_id == "img_b"
    assert found[FieldKey.MANUFACTURER_ADDRESS].parsed.pin == "422010"


def test_a_price_is_taken_from_the_image_that_actually_shows_it():
    """MRP clear in image 2 of 3, absent from 1 and 3."""
    doc = OcrDocument.build(
        [
            block("Best before 6 months from packing", 10, image="img1", conf=0.9),
            block("MRP Rs. 45.00 inclusive of all taxes", 10, image="img2", conf=0.95),
            block("Marketing claim: now tastier", 10, image="img3", conf=0.9),
        ]
    )
    mrp = extract_all(doc)[FieldKey.MRP]
    assert mrp.parsed.amount == 45.0
    assert mrp.parsed.inclusive_of_taxes is True
    assert mrp.image_id == "img2"


def test_a_blurred_price_does_not_override_a_clean_one_on_another_panel():
    """The same MRP on two panels: one read barely, one confidently. The evidence and
    confidence reported come from the clean panel even though the poor one appears
    first, and the one price is not mistaken for a dual declaration."""
    doc = OcrDocument.build(
        [
            block("MRP Rs. 45.00", 10, image="img1", conf=0.28),
            block("MRP Rs. 45.00 inclusive of all taxes", 10, image="img2", conf=0.97),
        ]
    )
    mrp = extract_all(doc)[FieldKey.MRP]
    assert mrp.image_id == "img2"
    assert mrp.confidence > 0.5
    assert mrp.parsed.inclusive_of_taxes is True
    assert mrp.parsed.all_amounts == (45.0,)


def test_a_field_absent_from_every_image_is_still_absent():
    """Reconciliation gives a field the benefit of all the evidence — it does not
    manufacture a value where no image shows one."""
    doc = OcrDocument.build(
        [
            block("Sunrise Foods", 10, image="img1", conf=0.95),
            block("Roasted Chana Masala", 40, image="img1", conf=0.95),
            block("Energy 402 kcal per 100 g", 10, image="img2", conf=0.95),
        ]
    )
    found = extract_all(doc)
    assert FieldKey.MRP not in found
    assert FieldKey.MFG_DATE not in found
