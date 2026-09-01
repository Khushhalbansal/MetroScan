from __future__ import annotations

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import pytest  # noqa: E402

from app.models.enums import Channel  # noqa: E402
from app.pipeline.declarations import DECLARATION_TYPES  # noqa: E402
from app.rules.loader import ruleset_for_date  # noqa: E402
from app.rules.schema import FieldValue, ScanContext  # noqa: E402
from app.rules.units import Basis  # noqa: E402


@pytest.fixture(scope="session")
def ruleset():
    return ruleset_for_date()


def field(key: str, text: str, /, *, conf: float = 0.95, **attrs) -> FieldValue:
    """Build one extracted declaration for a test.

    The parsed value is constructed through the real declaration type for this field,
    so a fixture cannot invent an attribute the extractor would never produce — that
    would be a test proving a rule works against data the pipeline cannot emit.
    Passing an unknown attribute is a TypeError here, at test-authoring time.
    """
    bbox = attrs.pop("bbox", [10.0, 10.0, 100.0, 20.0])
    h = attrs.pop("glyph_height_mm", None)
    w = attrs.pop("glyph_width_mm", None)

    kind = DECLARATION_TYPES.get(key)
    if kind is None:
        raise KeyError(f"no declaration type registered for field {key!r}")
    return FieldValue(
        key=key,
        raw_text=text,
        parsed=kind(**attrs),
        confidence=conf,
        bbox=bbox,
        image_id="img1",
        glyph_height_mm=h,
        glyph_width_mm=w,
    )


def compliant_context(**overrides) -> ScanContext:
    """A package that satisfies every rule — the baseline every test perturbs."""
    fields = {
        f.key: f
        for f in [
            field(
                "manufacturer_name", "Sunrise Foods Private Limited",
                text="Sunrise Foods Private Limited",
            ),
            # `pin` is what the extractor parses out of the address; rules read the
            # parsed value rather than re-matching the text (see normalized_present).
            field(
                "manufacturer_address",
                "Plot 14, MIDC Ambad, Nashik, Maharashtra 422010",
                pin="422010",
            ),
            field("common_name", "Roasted Chana", text="Roasted Chana"),
            field(
                "net_quantity", "Net Qty: 200 g", value=200, unit="g", basis=Basis.WEIGHT,
                glyph_height_mm=3.2, glyph_width_mm=1.6,
            ),
            field("mfg_date", "Mfd. 03/2026", month=3, year=2026),
            field(
                "mrp",
                "MRP ₹45.00 (inclusive of all taxes)",
                amount=45.0,
                all_amounts=(45.0,),
                # what the extractor captured, which is what the rules read
                currency_mark="₹",
                inclusive_of_taxes=True,
                glyph_height_mm=2.4,
                glyph_width_mm=1.1,
            ),
            field("consumer_care_name", "Consumer Care Cell", text="Consumer Care Cell"),
            field(
                "consumer_care_address", "Plot 14, MIDC Ambad, Nashik 422010",
                pin="422010",
            ),
            field(
                "consumer_care_phone", "1800 200 1234",
                digits="18002001234", glyph_height_mm=1.6,
            ),
            field(
                "consumer_care_email", "care@sunrisefoods.in",
                address="care@sunrisefoods.in",
            ),
            field("unit_sale_price", "₹0.23 per g", amount=0.225, per_unit="g"),
        ]
    }
    ctx = ScanContext(
        channel=Channel.PHYSICAL,
        is_imported=False,
        category="FOOD",
        fields=fields,
        mm_per_px=0.08,
        pdp_area_cm2=180.0,
        is_raised=False,
        semantic_flags={"misleading_claim": False},
        # This fixture models a label the scan actually read; a real capture of this
        # pack yields about this many text regions. Without it the engine correctly
        # refuses to call any declaration missing (see test_unreadable_input.py).
        blocks_read=15,
    )
    for k, v in overrides.items():
        setattr(ctx, k, v)
    return ctx
