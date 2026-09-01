"""Every rule gets a compliant fixture and at least one violating fixture.

These tests are the contract for the legal reasoning, so they assert on the exact
rule id and status, not on counts.
"""

from __future__ import annotations

import pytest
from conftest import compliant_context, field

from app.models.enums import Channel, FindingStatus, Severity, Verdict
from app.rules import units
from app.rules.engine import PASS_THRESHOLD, evaluate, score, verdict
from app.rules.loader import available_versions
from app.rules.schema import ScanContext
from app.rules.units import Basis


def judge(ctx: ScanContext, ruleset) -> dict[str, FindingStatus]:
    findings, _ = evaluate(ctx, ruleset)
    return {f.rule_id: f.status for f in findings}


def detail_for(ctx: ScanContext, ruleset, rule_id: str) -> dict:
    findings, _ = evaluate(ctx, ruleset)
    return next(f.detail for f in findings if f.rule_id == rule_id)


def message_for(ctx: ScanContext, ruleset, rule_id: str) -> str:
    findings, _ = evaluate(ctx, ruleset)
    return next(f.message for f in findings if f.rule_id == rule_id)


# --------------------------------------------------------------------- baseline


def test_ruleset_loads(ruleset):
    assert ruleset.version in available_versions()
    assert ruleset.rules, "ruleset has no rules"
    assert {"table_1", "table_2"} <= set(ruleset.tables)


def test_fully_compliant_package_passes_everything(ruleset):
    statuses = judge(compliant_context(), ruleset)
    unresolved = (FindingStatus.FAIL, FindingStatus.NEEDS_REVIEW)
    bad = {k: v for k, v in statuses.items() if v in unresolved}
    assert bad == {}, f"compliant baseline produced {bad}"


def test_compliant_package_scores_and_reads_compliant(ruleset):
    findings, _ = evaluate(compliant_context(), ruleset)
    value = score(findings)
    assert value == 100.0
    assert verdict(findings, value) is Verdict.COMPLIANT
    assert value >= PASS_THRESHOLD


def test_every_rule_has_an_implementation(ruleset):
    findings, _ = evaluate(compliant_context(), ruleset)
    unimplemented = [f.rule_id for f in findings if "No implementation" in f.message]
    assert unimplemented == []


def test_every_rule_is_reported_exactly_once(ruleset):
    findings, _ = evaluate(compliant_context(), ruleset)
    ids = [f.rule_id for f in findings]
    assert len(ids) == len(set(ids)) == len(ruleset.rules)


# --------------------------------------------------------------------- presence


@pytest.mark.parametrize(
    ("drop", "rule_id"),
    [
        ("manufacturer_name", "MANUFACTURER_NAME_PRESENT"),
        ("manufacturer_address", "MANUFACTURER_ADDRESS_PRESENT"),
        ("common_name", "COMMON_NAME_PRESENT"),
        ("net_quantity", "NET_QUANTITY_PRESENT"),
        ("mfg_date", "MFG_DATE_PRESENT"),
        ("mrp", "MRP_PRESENT"),
    ],
)
def test_missing_declaration_fails_its_rule(ruleset, drop, rule_id):
    ctx = compliant_context()
    del ctx.fields[drop]
    assert judge(ctx, ruleset)[rule_id] is FindingStatus.FAIL


def test_low_confidence_declaration_goes_to_review_not_failure(ruleset):
    ctx = compliant_context()
    ctx.fields["common_name"] = field(
        "common_name", "Roasted Chana", conf=0.31, text="Roasted Chana"
    )
    assert judge(ctx, ruleset)["COMMON_NAME_PRESENT"] is FindingStatus.NEEDS_REVIEW


# --------------------------------------------------------------------- consumer care


def test_consumer_care_absent_entirely_fails(ruleset):
    ctx = compliant_context()
    for k in list(ctx.fields):
        if k.startswith("consumer_care"):
            del ctx.fields[k]
    statuses = judge(ctx, ruleset)
    assert statuses["CONSUMER_CARE_PRESENT"] is FindingStatus.FAIL
    assert statuses["CONSUMER_CARE_COMPLETE"] is FindingStatus.FAIL


def test_consumer_care_missing_email_is_incomplete_but_present(ruleset):
    ctx = compliant_context()
    del ctx.fields["consumer_care_email"]
    statuses = judge(ctx, ruleset)
    assert statuses["CONSUMER_CARE_PRESENT"] is FindingStatus.PASS
    assert statuses["CONSUMER_CARE_COMPLETE"] is FindingStatus.FAIL
    assert "consumer care email" in message_for(ctx, ruleset, "CONSUMER_CARE_COMPLETE")


def test_incomplete_consumer_care_with_a_weak_read_goes_to_review(ruleset):
    """A part missing from a block whose visible parts read poorly is as likely an OCR
    miss as a genuine omission. One mangled sub-field ("ConsumerCare" at 0.75) and one
    lost to the address above it must go to an officer, not fail the pack."""
    ctx = compliant_context()
    del ctx.fields["consumer_care_address"]
    ctx.fields["consumer_care_name"] = field(
        "consumer_care_name", "ConsumerCare", conf=0.75, text="ConsumerCare"
    )
    assert judge(ctx, ruleset)["CONSUMER_CARE_COMPLETE"] is FindingStatus.NEEDS_REVIEW


def test_incomplete_consumer_care_read_cleanly_still_fails(ruleset):
    """The softening is confidence-gated: a clean read genuinely missing a part is
    still a failure, so the rule does not become a rubber stamp."""
    ctx = compliant_context()
    del ctx.fields["consumer_care_address"]
    assert judge(ctx, ruleset)["CONSUMER_CARE_COMPLETE"] is FindingStatus.FAIL


def test_malformed_consumer_care_email_fails_format(ruleset):
    ctx = compliant_context()
    ctx.fields["consumer_care_email"] = field(
        "consumer_care_email", "care.sunrisefoods", address=None
    )
    assert judge(ctx, ruleset)["CONSUMER_CARE_EMAIL_VALID"] is FindingStatus.FAIL


# --------------------------------------------------------------------- MRP


def test_mrp_without_inclusive_of_taxes_fails(ruleset):
    ctx = compliant_context()
    ctx.fields["mrp"] = field("mrp", "MRP ₹45.00", amount=45.0, all_amounts=(45.0,),
                                currency_mark="₹", inclusive_of_taxes=False)
    assert judge(ctx, ruleset)["MRP_INCLUSIVE_OF_TAXES"] is FindingStatus.FAIL


def test_dual_mrp_fails(ruleset):
    ctx = compliant_context()
    ctx.fields["mrp"] = field(
        "mrp",
        "MRP ₹45.00 / ₹50.00 inclusive of all taxes",
        amount=45.0,
        all_amounts=(45.0, 50.0),
        currency_mark="₹",
        inclusive_of_taxes=True,
    )
    statuses = judge(ctx, ruleset)
    assert statuses["MRP_SINGLE_VALUE"] is FindingStatus.FAIL
    assert "₹50.00" in message_for(ctx, ruleset, "MRP_SINGLE_VALUE")


def test_mrp_without_currency_marking_fails(ruleset):
    ctx = compliant_context()
    ctx.fields["mrp"] = field(
        "mrp", "MRP 45.00 inclusive of all taxes", amount=45.0, all_amounts=(45.0,),
        currency_mark=None, inclusive_of_taxes=True,
    )
    assert judge(ctx, ruleset)["MRP_CURRENCY_MARKED"] is FindingStatus.FAIL


@pytest.mark.parametrize(
    ("text", "mark"),
    [
        ("MRP Rs. 45.00 incl. of all taxes", "Rs."),
        ("MRP INR 45 inclusive of all taxes", "INR"),
    ],
)
def test_alternative_rupee_markings_pass(ruleset, text, mark):
    """That the extractor captures each spelling is covered in test_field_extraction;
    here the marking is supplied so the rule itself is what is under test."""
    ctx = compliant_context()
    ctx.fields["mrp"] = field(
        "mrp", text, amount=45.0, all_amounts=(45.0,), currency_mark=mark, inclusive_of_taxes=True
    )
    statuses = judge(ctx, ruleset)
    assert statuses["MRP_CURRENCY_MARKED"] is FindingStatus.PASS
    assert statuses["MRP_INCLUSIVE_OF_TAXES"] is FindingStatus.PASS


# --------------------------------------------------------------------- net quantity


def test_nonstandard_net_quantity_unit_fails(ruleset):
    ctx = compliant_context()
    ctx.fields["net_quantity"] = field(
        "net_quantity", "Net Qty 7 oz", value=7, unit="oz", basis=None
    )
    assert judge(ctx, ruleset)["NET_QUANTITY_UNIT_VALID"] is FindingStatus.FAIL


@pytest.mark.parametrize("unit", ["gms", "Kg", "ML", "litre", "pcs"])
def test_common_unit_spellings_are_accepted(ruleset, unit):
    ctx = compliant_context()
    ctx.fields["net_quantity"] = field(
        "net_quantity", f"Net Qty 200 {unit}", value=200,
        unit=units.canonical(unit), basis=units.basis_of(unit),
        glyph_height_mm=3.2, glyph_width_mm=1.6,
    )
    assert judge(ctx, ruleset)["NET_QUANTITY_UNIT_VALID"] is FindingStatus.PASS


# --------------------------------------------------------------------- mfg date


@pytest.mark.parametrize("text", ["Mfd. 03/2026", "PKD 03-26", "Manufactured MAR 2026"])
def test_valid_manufacture_dates_pass(ruleset, text):
    """Runs the real extractor rather than a fixture.

    MFG_DATE_FORMAT used to re-parse the raw text with its own date regex, so this
    test could pass while the extractor disagreed. The rule now reads the month and
    year the extractor parsed, so the only honest way to test these forms is to parse
    them for real.
    """
    from test_field_extraction import doc_from

    from app.pipeline.fields import extract_all

    extracted = extract_all(doc_from(text))["mfg_date"]
    ctx = compliant_context()
    ctx.fields["mfg_date"] = field(
        "mfg_date", text,
        month=extracted.parsed.month, year=extracted.parsed.year,
    )
    assert judge(ctx, ruleset)["MFG_DATE_FORMAT"] is FindingStatus.PASS


def test_year_only_manufacture_date_fails_format(ruleset):
    """Rule 6(1)(d) wants a month as well as a year."""
    ctx = compliant_context()
    ctx.fields["mfg_date"] = field("mfg_date", "Mfd. 2026", month=None, year=2026)
    assert judge(ctx, ruleset)["MFG_DATE_FORMAT"] is FindingStatus.FAIL


def test_month_only_manufacture_date_fails_format(ruleset):
    """The nearby edge: a month with no year is equally incomplete."""
    ctx = compliant_context()
    ctx.fields["mfg_date"] = field("mfg_date", "Mfd. MAR", month=3, year=None)
    assert judge(ctx, ruleset)["MFG_DATE_FORMAT"] is FindingStatus.FAIL


def test_half_read_manufacture_date_goes_to_review_not_failure(ruleset):
    """A date read weakly with only one component parsed is a bad read, not proof the
    label states half a date. Same softening as the completeness checks: a clean read
    still fails (above), a shaky one is an officer's call."""
    ctx = compliant_context()
    ctx.fields["mfg_date"] = field("mfg_date", "Mfd. 20Z6", conf=0.7, month=3, year=None)
    assert judge(ctx, ruleset)["MFG_DATE_FORMAT"] is FindingStatus.NEEDS_REVIEW


# --------------------------------------------------------------------- Rule 8 geometry


def test_undersized_net_quantity_numerals_fail_with_the_measurement(ruleset):
    ctx = compliant_context()
    ctx.fields["net_quantity"].glyph_height_mm = 1.2  # 180 cm2 panel requires 2.0 mm
    statuses = judge(ctx, ruleset)
    assert statuses["FONT_HEIGHT_NET_QUANTITY"] is FindingStatus.FAIL
    detail = detail_for(ctx, ruleset, "FONT_HEIGHT_NET_QUANTITY")
    assert detail["measured_mm"] == 1.2
    assert detail["required_mm"] == 2.0
    assert detail["table"] == "Rule 8, Table I"


def test_height_inside_measurement_tolerance_goes_to_review(ruleset):
    ctx = compliant_context()
    ctx.fields["net_quantity"].glyph_height_mm = 1.87  # within 10% of 2.0
    assert judge(ctx, ruleset)["FONT_HEIGHT_NET_QUANTITY"] is FindingStatus.NEEDS_REVIEW


@pytest.mark.parametrize(
    ("area", "required"),
    [(40.0, 1.0), (80.0, 1.5), (180.0, 2.0), (900.0, 4.0), (4000.0, 6.0)],
)
def test_table_one_bands(ruleset, area, required):
    ctx = compliant_context(pdp_area_cm2=area)
    ctx.fields["net_quantity"].glyph_height_mm = required
    assert judge(ctx, ruleset)["FONT_HEIGHT_NET_QUANTITY"] is FindingStatus.PASS
    assert detail_for(ctx, ruleset, "FONT_HEIGHT_NET_QUANTITY")["required_mm"] == required


def test_embossed_packages_need_the_raised_height(ruleset):
    ctx = compliant_context(is_raised=True)
    ctx.fields["net_quantity"].glyph_height_mm = 2.5  # fine when printed, short when moulded
    assert judge(ctx, ruleset)["FONT_HEIGHT_NET_QUANTITY"] is FindingStatus.FAIL
    assert detail_for(ctx, ruleset, "FONT_HEIGHT_NET_QUANTITY")["required_mm"] == 4.0


def test_count_declarations_use_table_two(ruleset):
    ctx = compliant_context(pdp_area_cm2=80.0)
    ctx.fields["net_quantity"] = field(
        "net_quantity", "10 pcs", value=10, unit="pcs", basis=Basis.NUMBER,
        glyph_height_mm=1.0, glyph_width_mm=0.5
    )
    detail = detail_for(ctx, ruleset, "FONT_HEIGHT_NET_QUANTITY")
    assert detail["table"] == "Rule 8, Table II"
    assert detail["required_mm"] == 1.0  # Table II allows 1 mm up to 100 cm2


def test_geometry_without_a_scale_reference_is_never_a_failure(ruleset):
    ctx = compliant_context(mm_per_px=None)
    ctx.fields["net_quantity"].glyph_height_mm = 0.2
    statuses = judge(ctx, ruleset)
    for rule_id in ("FONT_HEIGHT_NET_QUANTITY", "FONT_HEIGHT_MINIMUM", "FONT_WIDTH_RATIO"):
        assert statuses[rule_id] is FindingStatus.NEEDS_REVIEW
    assert "scale reference" in message_for(ctx, ruleset, "FONT_HEIGHT_NET_QUANTITY")


def test_geometry_without_panel_area_is_never_a_failure(ruleset):
    ctx = compliant_context(pdp_area_cm2=None)
    assert judge(ctx, ruleset)["FONT_HEIGHT_NET_QUANTITY"] is FindingStatus.NEEDS_REVIEW


def test_sub_millimetre_lettering_fails_the_absolute_minimum(ruleset):
    ctx = compliant_context()
    ctx.fields["consumer_care_phone"].glyph_height_mm = 0.6
    statuses = judge(ctx, ruleset)
    assert statuses["FONT_HEIGHT_MINIMUM"] is FindingStatus.FAIL
    assert detail_for(ctx, ruleset, "FONT_HEIGHT_MINIMUM")["field"] == "consumer_care_phone"


def test_over_condensed_lettering_fails_the_width_ratio(ruleset):
    ctx = compliant_context()
    ctx.fields["net_quantity"].glyph_width_mm = 0.6  # 0.6/3.2 = 0.19
    assert judge(ctx, ruleset)["FONT_WIDTH_RATIO"] is FindingStatus.FAIL


# --------------------------------------------------------------------- imports


def test_imported_package_without_country_of_origin_fails(ruleset):
    ctx = compliant_context(is_imported=True)
    assert judge(ctx, ruleset)["COUNTRY_OF_ORIGIN_PRESENT"] is FindingStatus.FAIL


def test_country_of_origin_is_not_required_for_domestic_packages(ruleset):
    assert judge(compliant_context(), ruleset)["COUNTRY_OF_ORIGIN_PRESENT"] is FindingStatus.NA


def test_imported_package_with_country_of_origin_passes(ruleset):
    ctx = compliant_context(is_imported=True)
    ctx.fields["country_of_origin"] = field(
        "country_of_origin", "Country of Origin: Vietnam", country="Vietnam"
    )
    assert judge(ctx, ruleset)["COUNTRY_OF_ORIGIN_PRESENT"] is FindingStatus.PASS


# --------------------------------------------------------------------- unit sale price


def test_missing_unit_sale_price_fails(ruleset):
    ctx = compliant_context()
    del ctx.fields["unit_sale_price"]
    assert judge(ctx, ruleset)["UNIT_SALE_PRICE_PRESENT"] is FindingStatus.FAIL


def test_unit_sale_price_inconsistent_with_mrp_fails(ruleset):
    ctx = compliant_context()
    ctx.fields["unit_sale_price"] = field(
        "unit_sale_price", "₹0.90 per g", amount=0.90, per_unit="g"
    )
    assert judge(ctx, ruleset)["UNIT_SALE_PRICE_PRESENT"] is FindingStatus.FAIL
    assert "do not agree" in message_for(ctx, ruleset, "UNIT_SALE_PRICE_PRESENT").replace(
        "does not agree", "do not agree"
    )


def test_single_gram_pack_does_not_need_a_unit_sale_price(ruleset):
    ctx = compliant_context()
    ctx.fields["net_quantity"] = field(
        "net_quantity", "1 g", value=1, unit="g", basis=Basis.WEIGHT,
        glyph_height_mm=3.0, glyph_width_mm=1.5
    )
    del ctx.fields["unit_sale_price"]
    assert judge(ctx, ruleset)["UNIT_SALE_PRICE_PRESENT"] is FindingStatus.NA


def test_kilogram_pack_unit_price_is_computed_per_kilogram(ruleset):
    ctx = compliant_context()
    ctx.fields["net_quantity"] = field(
        "net_quantity", "2 kg", value=2, unit="kg", basis=Basis.WEIGHT,
        glyph_height_mm=3.2, glyph_width_mm=1.6
    )
    ctx.fields["mrp"] = field(
        "mrp", "MRP ₹300.00 inclusive of all taxes", amount=300.0,
        all_amounts=(300.0,), currency_mark="₹", inclusive_of_taxes=True,
        glyph_height_mm=2.4, glyph_width_mm=1.1,
    )
    ctx.fields["unit_sale_price"] = field(
        "unit_sale_price", "₹150 per kg", amount=150.0, per_unit="kg"
    )
    assert judge(ctx, ruleset)["UNIT_SALE_PRICE_PRESENT"] is FindingStatus.PASS


# --------------------------------------------------------------------- Rule 26 exemptions


def test_sachet_under_ten_grams_is_exempt_from_most_declarations(ruleset):
    ctx = compliant_context()
    ctx.fields["net_quantity"] = field(
        "net_quantity", "8 g", value=8, unit="g", basis=Basis.WEIGHT,
        glyph_height_mm=3.0, glyph_width_mm=1.5
    )
    findings, exemption = evaluate(ctx, ruleset)
    assert exemption is not None and exemption.id == "SMALL_PACKAGE"
    statuses = {f.rule_id: f.status for f in findings}
    assert statuses["MANUFACTURER_NAME_PRESENT"] is FindingStatus.NA
    # net quantity and price are never exempt
    assert statuses["NET_QUANTITY_PRESENT"] is FindingStatus.PASS
    assert statuses["MRP_PRESENT"] is FindingStatus.PASS


def test_tobacco_sachet_is_not_exempt(ruleset):
    ctx = compliant_context(category="TOBACCO")
    ctx.fields["net_quantity"] = field(
        "net_quantity", "8 g", value=8, unit="g", basis=Basis.WEIGHT,
        glyph_height_mm=3.0, glyph_width_mm=1.5
    )
    _, exemption = evaluate(ctx, ruleset)
    assert exemption is None


def test_bulk_agricultural_package_is_exempt(ruleset):
    ctx = compliant_context(category="AGRICULTURAL")
    ctx.fields["net_quantity"] = field(
        "net_quantity", "60 kg", value=60, unit="kg", basis=Basis.WEIGHT,
        glyph_height_mm=6.0, glyph_width_mm=3.0
    )
    _, exemption = evaluate(ctx, ruleset)
    assert exemption is not None and exemption.id == "BULK_AGRICULTURAL"


# --------------------------------------------------------------------- e-commerce


def test_listing_does_not_need_a_manufacture_date(ruleset):
    ctx = compliant_context(channel=Channel.ECOMMERCE)
    del ctx.fields["mfg_date"]
    statuses = judge(ctx, ruleset)
    assert statuses["MFG_DATE_PRESENT"] is FindingStatus.NA
    assert statuses["ECOMMERCE_DECLARATIONS_DISPLAYED"] is FindingStatus.PASS


def test_listing_missing_net_quantity_fails_the_ecommerce_rule(ruleset):
    ctx = compliant_context(channel=Channel.ECOMMERCE)
    del ctx.fields["net_quantity"]
    assert judge(ctx, ruleset)["ECOMMERCE_DECLARATIONS_DISPLAYED"] is FindingStatus.FAIL


def test_geometry_rules_do_not_apply_to_listings(ruleset):
    ctx = compliant_context(channel=Channel.ECOMMERCE)
    statuses = judge(ctx, ruleset)
    for rule_id in ("FONT_HEIGHT_NET_QUANTITY", "FONT_HEIGHT_MINIMUM", "FONT_WIDTH_RATIO"):
        assert statuses[rule_id] is FindingStatus.NA


# --------------------------------------------------------------------- Rule 9


def test_misleading_claim_flag_fails_rule_nine(ruleset):
    ctx = compliant_context()
    ctx.semantic_flags = {
        "misleading_claim": True,
        "misleading_claim_detail": "Claims “100% natural” alongside a synthetic colour.",
    }
    assert judge(ctx, ruleset)["NO_MISLEADING_DECLARATION"] is FindingStatus.FAIL
    assert "100% natural" in message_for(ctx, ruleset, "NO_MISLEADING_DECLARATION")


def test_unassessed_claims_go_to_review(ruleset):
    ctx = compliant_context()
    ctx.semantic_flags = {}
    assert judge(ctx, ruleset)["NO_MISLEADING_DECLARATION"] is FindingStatus.NEEDS_REVIEW


def test_low_confidence_reads_raise_a_legibility_review(ruleset):
    ctx = compliant_context()
    ctx.fields["mfg_date"] = field("mfg_date", "Mfd. 03/2026", conf=0.22, month=3, year=2026)
    assert judge(ctx, ruleset)["DECLARATIONS_LEGIBLE"] is FindingStatus.NEEDS_REVIEW


# --------------------------------------------------------------------- scoring


def test_a_critical_failure_makes_the_package_non_compliant(ruleset):
    ctx = compliant_context()
    del ctx.fields["mrp"]
    findings, _ = evaluate(ctx, ruleset)
    assert verdict(findings, score(findings)) is Verdict.NON_COMPLIANT


def test_open_review_items_make_the_verdict_inconclusive(ruleset):
    ctx = compliant_context(mm_per_px=None)
    findings, _ = evaluate(ctx, ruleset)
    assert verdict(findings, score(findings)) is Verdict.INCONCLUSIVE


def test_score_falls_further_for_critical_than_for_minor_failures(ruleset):
    minor = compliant_context()
    minor.fields["mrp"] = field(
        "mrp", "MRP 45.00 inclusive of all taxes", amount=45.0, all_amounts=(45.0,),
        currency_mark=None, inclusive_of_taxes=True,
        glyph_height_mm=2.4, glyph_width_mm=1.1,
    )  # trips MRP_CURRENCY_MARKED, a MINOR
    critical = compliant_context()
    del critical.fields["manufacturer_name"]

    minor_score = score(evaluate(minor, ruleset)[0])
    critical_score = score(evaluate(critical, ruleset)[0])
    assert 0 < critical_score < minor_score < 100


def test_severity_weights_are_reflected_in_the_findings(ruleset):
    findings, _ = evaluate(compliant_context(), ruleset)
    by_id = {f.rule_id: f for f in findings}
    assert by_id["MRP_PRESENT"].severity is Severity.CRITICAL
    assert by_id["MRP_CURRENCY_MARKED"].severity is Severity.MINOR


def test_failures_carry_remediation_and_passes_do_not(ruleset):
    ctx = compliant_context()
    del ctx.fields["mrp"]
    findings, _ = evaluate(ctx, ruleset)
    failed = next(f for f in findings if f.rule_id == "MRP_PRESENT")
    passed = next(f for f in findings if f.rule_id == "NET_QUANTITY_PRESENT")
    assert failed.remediation and "inclusive of all taxes" in failed.remediation
    assert passed.remediation is None


def test_every_finding_cites_a_rule(ruleset):
    findings, _ = evaluate(compliant_context(), ruleset)
    assert all(f.citation.startswith("Rule ") for f in findings)


def test_a_broken_rule_does_not_sink_the_scan(ruleset):
    ctx = compliant_context()
    ctx.fields["net_quantity"] = field(
        "net_quantity", "Net Qty ??? g", value="not-a-number", unit="g", basis=Basis.WEIGHT
    )
    findings, _ = evaluate(ctx, ruleset)
    assert len(findings) == len(ruleset.rules)


# ------------------------------------------- rules read parsed values, not raw text


def test_address_completeness_uses_the_parsed_pin(ruleset):
    """OCR drops the space before a PIN more often than not. The rule must read the
    PIN the extractor parsed rather than re-matching the raw text, or a complete
    address is reported incomplete."""
    ctx = compliant_context()
    ctx.fields["manufacturer_address"] = field(
        "manufacturer_address", "Plot 14, MIDC Ambad Nashik,Maharashtra422010", pin="422010"
    )
    assert judge(ctx, ruleset)["MANUFACTURER_ADDRESS_COMPLETE"] is FindingStatus.PASS


@pytest.mark.parametrize(
    "written",
    ["Nashik, Maharashtra 422010", "Nashik,Maharashtra422010", "Nashik MH - 422 010"],
)
def test_every_way_a_pin_is_printed_satisfies_the_rule(ruleset, written):
    from app.pipeline.fields import _pin

    ctx = compliant_context()
    ctx.fields["manufacturer_address"] = field(
        "manufacturer_address", f"Plot 14, {written}", pin=_pin(written)
    )
    assert judge(ctx, ruleset)["MANUFACTURER_ADDRESS_COMPLETE"] is FindingStatus.PASS


def test_an_address_with_no_pin_at_all_still_fails(ruleset):
    """The fix must not turn the rule into a rubber stamp."""
    ctx = compliant_context()
    ctx.fields["manufacturer_address"] = field(
        "manufacturer_address", "Plot 14, MIDC Ambad, Nashik", pin=None
    )
    assert judge(ctx, ruleset)["MANUFACTURER_ADDRESS_COMPLETE"] is FindingStatus.FAIL


def test_a_low_confidence_address_without_a_pin_goes_to_review(ruleset):
    ctx = compliant_context()
    ctx.fields["manufacturer_address"] = field(
        "manufacturer_address", "Pl0t l4, M1DC Ambad", conf=0.3, pin=None
    )
    assert judge(ctx, ruleset)["MANUFACTURER_ADDRESS_COMPLETE"] is FindingStatus.NEEDS_REVIEW


def test_currency_marking_rule_uses_the_captured_mark(ruleset):
    """OCR glues "MRP" to "Rs." often enough that a raw-text word boundary cannot be
    relied on to find the marking."""
    ctx = compliant_context()
    ctx.fields["mrp"] = field(
        "mrp", "MRPRs.45.00 (inclusive of all taxes)",
        amount=45.0, all_amounts=(45.0,), currency_mark="Rs.", inclusive_of_taxes=True,
    )
    assert judge(ctx, ruleset)["MRP_CURRENCY_MARKED"] is FindingStatus.PASS


def test_a_price_genuinely_without_a_marking_still_fails(ruleset):
    ctx = compliant_context()
    ctx.fields["mrp"] = field(
        "mrp", "MRP 45.00 inclusive of all taxes",
        amount=45.0, all_amounts=(45.0,), currency_mark=None, inclusive_of_taxes=True,
    )
    assert judge(ctx, ruleset)["MRP_CURRENCY_MARKED"] is FindingStatus.FAIL
