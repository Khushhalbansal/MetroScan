"""The boundary between evidence and fact, enforced.

`raw_text` is what the officer is shown. `parsed` is what the rules judge. Every
false violation this pipeline produced came from a rule crossing that line and
re-deriving a fact the extractor had already parsed, with boundary assumptions real
OCR output violates.

These tests hold the boundary shut: a rule cannot carry a regex, cannot name an
attribute that does not exist, and cannot silently read None from a typo.
"""

from __future__ import annotations

import dataclasses
import pathlib

import pytest
from conftest import compliant_context, field

from app.models.enums import FindingStatus
from app.pipeline.declarations import (
    DECLARATION_TYPES,
    AddressDeclaration,
    PriceDeclaration,
    attributes_of,
)
from app.rules.engine import evaluate
from app.rules.loader import RulesetContractError, parse_ruleset, validate_contract
from app.rules.schema import FieldValue, Rule

# ------------------------------------------------- rules cannot carry raw patterns


def test_a_rule_cannot_carry_a_regex_at_all():
    """The strongest form of the fix: there is no field for a pattern to live in."""
    names = {f.name for f in dataclasses.fields(Rule)}
    assert "pattern" not in names
    assert "normalized_key" not in names


def test_no_check_kind_matches_raw_text():
    """`format`, `normalized_present` and `mfg_date_format` each re-parsed raw text
    and each eventually disagreed with the extractor."""
    from app.rules.engine import CHECKS

    for retired in ("format", "normalized_present", "mfg_date_format"):
        assert retired not in CHECKS


def test_the_shipped_ruleset_uses_no_retired_check(ruleset):
    for rule in ruleset.rules:
        assert rule.check not in ("format", "normalized_present", "mfg_date_format")


# --------------------------------------------------------- load-time validation


def _ruleset_with(**rule_fields) -> dict:
    base = {
        "meta": {"version": "test", "effective_date": "2022-04-01"},
        "geometry_tables": {
            "table_1": {
                "citation": "Rule 8, Table I",
                "basis": ["WEIGHT"],
                "bands": [{"max_cm2": None, "normal_mm": 1.0, "raised_mm": 2.0}],
            }
        },
        "rules": [
            {
                "id": "TEST_RULE",
                "title": "test",
                "citation": "Rule 6(1)(a)",
                "severity": "MINOR",
                "applies_to": ["PHYSICAL"],
                "message_fail": "nope",
                **rule_fields,
            }
        ],
    }
    return base


def test_a_mistyped_attribute_fails_at_load_not_at_scan_time():
    """The whole point. `pinn` used to read back as None, which is indistinguishable
    from "the package has no PIN" — so a typo condemned every pack scanned."""
    bad = parse_ruleset(
        _ruleset_with(check="attribute", field="manufacturer_address", attributes=["pinn"])
    )
    with pytest.raises(RulesetContractError, match="pinn"):
        validate_contract(bad)


def test_the_error_names_the_attributes_that_do_exist():
    bad = parse_ruleset(
        _ruleset_with(check="attribute", field="mrp", attributes=["inclusive_of_tax"])
    )
    with pytest.raises(RulesetContractError, match="currency_mark"):
        validate_contract(bad)


def test_a_rule_naming_an_unknown_field_fails_at_load():
    bad = parse_ruleset(
        _ruleset_with(check="attribute", field="net_wieght", attributes=["value"])
    )
    with pytest.raises(RulesetContractError, match="net_wieght"):
        validate_contract(bad)


def test_an_attribute_check_without_attributes_fails_at_load():
    bad = parse_ruleset(_ruleset_with(check="attribute", field="mrp"))
    with pytest.raises(RulesetContractError, match="at least one attribute"):
        validate_contract(bad)


def test_attributes_on_a_check_that_ignores_them_fails_at_load():
    """Otherwise the attributes are silently dead config that reads as enforced."""
    bad = parse_ruleset(_ruleset_with(check="presence", field="mrp", attributes=["amount"]))
    with pytest.raises(RulesetContractError, match="does not use attributes"):
        validate_contract(bad)


def test_the_shipped_ruleset_satisfies_its_own_contract(ruleset):
    validate_contract(ruleset)  # must not raise


def test_every_field_a_rule_names_has_a_declaration_type(ruleset):
    for rule in ruleset.rules:
        for key in (k for k in (rule.field_key, *rule.field_keys) if k):
            assert key in DECLARATION_TYPES, f"{rule.id} names {key} with no parsed type"


# ------------------------------------------------- attribute access is not silent


def test_reading_an_unknown_attribute_raises_rather_than_returning_none():
    value = field("manufacturer_address", "Nashik 422010", pin="422010")
    assert value.attribute("pin") == "422010"
    with pytest.raises(AttributeError, match="pinn"):
        value.attribute("pinn")


def test_the_error_lists_the_known_attributes():
    with pytest.raises(AttributeError, match="currency_mark"):
        PriceDeclaration(amount=45.0).attribute("currancy_mark")


def test_an_unparsed_declaration_reads_as_none_not_an_error():
    """A field the extractor located but could not parse is a real state."""
    value = FieldValue(key="mrp", raw_text="MRP ?????", parsed=None)
    assert value.attribute("amount") is None


def test_declaration_types_expose_their_attributes():
    assert attributes_of("mrp") == PriceDeclaration.attributes()
    assert "pin" in attributes_of("manufacturer_address")
    assert attributes_of("no_such_field") == frozenset()


# -------------------------------------------------- behaviour through the engine


def test_a_parsed_attribute_drives_the_finding(ruleset):
    ctx = compliant_context()
    ctx.fields["manufacturer_address"] = field(
        "manufacturer_address", "Plot 14, MIDC Ambad Nashik", pin=None
    )
    findings = {f.rule_id: f for f in evaluate(ctx, ruleset)[0]}
    assert findings["MANUFACTURER_ADDRESS_COMPLETE"].status is FindingStatus.FAIL
    assert findings["MANUFACTURER_ADDRESS_COMPLETE"].detail["missing_attributes"] == ["pin"]


def test_raw_text_shape_no_longer_changes_the_verdict(ruleset):
    """The same parsed facts, printed three ways OCR mangles differently.

    Every one of these spellings previously broke a rule that re-read the text:
    the glued PIN, the glued rupee marking, the spaced PIN.
    """
    spellings = [
        ("Plot 14, Nashik, Maharashtra 422010", "MRP Rs. 45.00 (inclusive of all taxes)"),
        ("Plot 14, Nashik,Maharashtra422010", "MRPRs.45.00(inclusive of all taxes)"),
        ("Plot 14, Nashik MH - 422 010", "M.R.P.Rs45.00 incl. of all taxes"),
    ]
    verdicts = []
    for address, price in spellings:
        ctx = compliant_context()
        ctx.fields["manufacturer_address"] = field(
            "manufacturer_address", address, pin="422010"
        )
        ctx.fields["mrp"] = field(
            "mrp", price, amount=45.0, all_amounts=(45.0,),
            currency_mark="Rs.", inclusive_of_taxes=True,
            glyph_height_mm=2.4, glyph_width_mm=1.1,
        )
        findings = evaluate(ctx, ruleset)[0]
        verdicts.append({f.rule_id: f.status for f in findings})

    assert verdicts[0] == verdicts[1] == verdicts[2]
    assert all(v["MANUFACTURER_ADDRESS_COMPLETE"] is FindingStatus.PASS for v in verdicts)
    assert all(v["MRP_CURRENCY_MARKED"] is FindingStatus.PASS for v in verdicts)
    assert all(v["MRP_INCLUSIVE_OF_TAXES"] is FindingStatus.PASS for v in verdicts)


def test_a_weakly_read_declaration_that_will_not_parse_goes_to_review(ruleset):
    """Uncertain must never become a violation."""
    ctx = compliant_context()
    ctx.fields["manufacturer_address"] = field(
        "manufacturer_address", "Pl0t l4, M1DC", conf=0.30, pin=None
    )
    findings = {f.rule_id: f.status for f in evaluate(ctx, ruleset)[0]}
    assert findings["MANUFACTURER_ADDRESS_COMPLETE"] is FindingStatus.NEEDS_REVIEW


def test_declarations_are_immutable_once_parsed():
    """A rule must not be able to edit the facts it is judging."""
    parsed = AddressDeclaration(pin="422010")
    with pytest.raises(dataclasses.FrozenInstanceError):
        parsed.pin = "999999"  # type: ignore[misc]


def test_the_rule_engine_imports_no_regex_module():
    """A structural guard on the boundary.

    With every raw-text check retired, the engine has no reason to hold a regex. If
    `re` reappears here it means judgement has started re-parsing text the extractor
    already parsed — the exact regression this refactor exists to prevent.
    """
    import app.rules.engine as engine_module

    source = pathlib.Path(engine_module.__file__).read_text(encoding="utf-8")
    assert "import re" not in source, "the rule engine has started matching text again"


# ------------------------- a missing attribute is still a claim about the label


def test_a_missing_attribute_is_not_asserted_on_a_barely_read_label(ruleset):
    """An attribute is part of a declaration, so its absence is a negative claim.

    A scan that read two blocks off one corner of a pack cannot testify that the tax
    rider is not printed further down. This used to FAIL MRP_INCLUSIVE_OF_TAXES on a
    two-block scan, condemning a pack the camera had barely seen.
    """
    ctx = compliant_context()
    ctx.blocks_read = 2
    ctx.fields = {
        "mrp": field(
            "mrp", "MRP Rs. 45.00", amount=45.0, all_amounts=(45.0,),
            currency_mark="Rs.", inclusive_of_taxes=False,
        )
    }
    statuses = {f.rule_id: f.status for f in evaluate(ctx, ruleset)[0]}
    assert statuses["MRP_INCLUSIVE_OF_TAXES"] is FindingStatus.NEEDS_REVIEW


@pytest.mark.parametrize(
    ("rule_id", "key", "attrs"),
    [
        ("MRP_INCLUSIVE_OF_TAXES", "mrp", {"inclusive_of_taxes": False}),
        ("MRP_CURRENCY_MARKED", "mrp", {"currency_mark": None}),
        ("MANUFACTURER_ADDRESS_COMPLETE", "manufacturer_address", {"pin": None}),
        ("MFG_DATE_FORMAT", "mfg_date", {"month": None, "year": None}),
    ],
)
def test_no_attribute_rule_asserts_absence_without_support(ruleset, rule_id, key, attrs):
    """The whole class, not the one instance that showed up in the fuzz."""
    ctx = compliant_context()
    ctx.blocks_read = 2
    ctx.fields = {key: field(key, "something", **attrs)}
    statuses = {f.rule_id: f.status for f in evaluate(ctx, ruleset)[0]}
    assert statuses[rule_id] is FindingStatus.NEEDS_REVIEW


def test_a_fully_read_label_still_fails_a_genuinely_missing_attribute(ruleset):
    """The guard must not become a blanket excuse."""
    ctx = compliant_context()  # blocks_read = 15, many fields
    ctx.fields["mrp"] = field(
        "mrp", "MRP Rs. 45.00", amount=45.0, all_amounts=(45.0,),
        currency_mark="Rs.", inclusive_of_taxes=False,
        glyph_height_mm=2.4, glyph_width_mm=1.1,
    )
    statuses = {f.rule_id: f.status for f in evaluate(ctx, ruleset)[0]}
    assert statuses["MRP_INCLUSIVE_OF_TAXES"] is FindingStatus.FAIL
