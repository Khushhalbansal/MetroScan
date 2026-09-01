"""Whole-pipeline tests: rendered label -> OCR -> measurement -> findings.

These run the real OCR engine against labels whose ground truth is known by
construction, so they check the thing that actually ships rather than a mock of it.
"""

from __future__ import annotations

import pytest

pytest.importorskip("cv2", reason="OpenCV is required for the end-to-end tests")

from app.models.enums import FieldKey, FindingStatus, Verdict
from app.pipeline import synth
from app.pipeline.engine_ocr import get_engine
from app.pipeline.runner import ScanInput, run_scan
from app.pipeline.scale import ScaleSource

pytestmark = pytest.mark.slow


@pytest.fixture(scope="module")
def ocr():
    engine = get_engine()
    if engine.name == "stub":
        pytest.skip("OCR weights unavailable")
    return engine


def scan(spec, **kw):
    image = synth.render(spec)
    return run_scan([ScanInput(image=image, image_id="img1")], **kw)


def statuses(outcome) -> dict[str, FindingStatus]:
    return {f.rule_id: f.status for f in outcome.findings}


@pytest.fixture(scope="module")
def compliant(ocr):
    return scan(synth.compliant_label())


# ------------------------------------------------------------------ the good case


def test_reads_a_rendered_label(compliant):
    assert len(compliant.ocr_blocks) >= 10


def test_recovers_the_scale_from_the_card(compliant):
    assert compliant.scale.source is ScaleSource.ARUCO
    # The label is rendered at 12 px per mm, so the true scale is 1/12.
    assert compliant.scale.mm_per_px == pytest.approx(1 / 12, rel=0.05)
    assert compliant.scale.confidence > 0.8


def test_finds_every_mandatory_declaration(compliant):
    required = {
        FieldKey.MANUFACTURER_NAME,
        FieldKey.MANUFACTURER_ADDRESS,
        FieldKey.NET_QUANTITY,
        FieldKey.MRP,
        FieldKey.MFG_DATE,
        FieldKey.CONSUMER_CARE_EMAIL,
        FieldKey.CONSUMER_CARE_PHONE,
        FieldKey.UNIT_SALE_PRICE,
    }
    assert required <= set(compliant.fields)


def test_measures_type_size_against_what_was_rendered(compliant):
    net = compliant.fields[FieldKey.NET_QUANTITY]
    # Rendered at 3.0 mm by COMPLIANT_DECLARATIONS.
    assert net.glyph_height_mm == pytest.approx(3.0, rel=0.15)


def test_a_compliant_label_raises_no_failures(compliant):
    failures = {r: s for r, s in statuses(compliant).items() if s is FindingStatus.FAIL}
    assert failures == {}


def test_a_compliant_label_scores_full_marks(compliant):
    assert compliant.compliance_score == 100.0


def test_rule_nine_is_left_for_review_when_nothing_assessed_claims(compliant):
    """Offline, the system cannot clear a misleading-claim rule, and says so."""
    assert statuses(compliant)["NO_MISLEADING_DECLARATION"] is FindingStatus.NEEDS_REVIEW
    assert compliant.verdict is Verdict.INCONCLUSIVE


def test_supplying_a_semantic_judgement_reaches_a_verdict():
    outcome = scan(synth.compliant_label(), semantic_flags={"misleading_claim": False})
    assert outcome.verdict is Verdict.COMPLIANT


def test_batch_number_is_not_confused_with_a_street_number(compliant):
    """'Plot 14' contains 'lot'; the batch number is RC2603A."""
    batch = compliant.fields.get(FieldKey.BATCH_NUMBER)
    if batch is not None:
        assert batch.raw_text != "14"
        assert batch.raw_text.upper().startswith("RC")


def test_a_correctly_rounded_unit_price_is_accepted(compliant):
    """45.00 / 200 g = 0.225, which can only be printed as 0.23."""
    assert statuses(compliant)["UNIT_SALE_PRICE_PRESENT"] is FindingStatus.PASS


def test_every_finding_can_be_traced_to_the_image(compliant):
    located = [f for f in compliant.findings if f.evidence_bbox]
    assert located, "no finding carried evidence coordinates"
    for finding in located:
        x, y, w, h = finding.evidence_bbox
        assert w > 0 and h > 0
        assert finding.evidence_image_id == "img1"


# ------------------------------------------------------------- injected violations


@pytest.mark.parametrize(
    ("violation", "rule_id"),
    [
        ("missing_mrp", "MRP_PRESENT"),
        ("no_tax_phrase", "MRP_INCLUSIVE_OF_TAXES"),
        ("dual_mrp", "MRP_SINGLE_VALUE"),
        ("missing_mfg_date", "MFG_DATE_PRESENT"),
        ("missing_manufacturer", "MANUFACTURER_NAME_PRESENT"),
        ("missing_consumer_care_email", "CONSUMER_CARE_COMPLETE"),
        ("undersized_net_quantity", "FONT_HEIGHT_NET_QUANTITY"),
    ],
)
def test_injected_violation_is_caught(ocr, violation, rule_id):
    outcome = scan(synth.label_with({violation}))
    assert statuses(outcome)[rule_id] is FindingStatus.FAIL, (
        f"{violation} did not trip {rule_id}; "
        f"read: {sorted(outcome.fields)}"
    )


def test_undersized_print_reports_the_measurement(ocr):
    outcome = scan(synth.label_with({"undersized_net_quantity"}))
    finding = next(f for f in outcome.findings if f.rule_id == "FONT_HEIGHT_NET_QUANTITY")
    assert finding.status is FindingStatus.FAIL
    assert finding.detail["measured_mm"] < finding.detail["required_mm"]
    assert finding.detail["table"].startswith("Rule 8")


def test_a_violating_label_is_non_compliant(ocr):
    outcome = scan(synth.label_with({"missing_mrp"}))
    assert outcome.verdict is Verdict.NON_COMPLIANT
    assert outcome.compliance_score < 100.0


def test_several_violations_score_lower_than_one(ocr):
    one = scan(synth.label_with({"no_tax_phrase"}))
    many = scan(synth.label_with({"missing_mrp", "missing_mfg_date", "missing_manufacturer"}))
    assert many.compliance_score < one.compliance_score


# ------------------------------------------------------------------- no fiducial


def test_without_a_scale_card_geometry_is_reviewed_not_failed(ocr):
    spec = synth.compliant_label()
    spec.with_scale_card = False
    outcome = scan(spec)
    assert not outcome.scale.usable
    assert statuses(outcome)["FONT_HEIGHT_NET_QUANTITY"] is FindingStatus.NEEDS_REVIEW
    assert any("scale reference" in n for n in outcome.notes)


def test_declarations_are_still_read_without_a_scale_card(ocr):
    spec = synth.compliant_label()
    spec.with_scale_card = False
    outcome = scan(spec)
    assert FieldKey.MRP in outcome.fields
    assert FieldKey.NET_QUANTITY in outcome.fields


# ---------------------------------------------------------------------- metadata


def test_outcome_records_how_it_was_produced(compliant):
    assert compliant.ruleset_version
    assert "rapidocr" in compliant.extractor_version
    assert compliant.pdp_area_cm2 and compliant.pdp_area_cm2 > 0


def test_an_empty_submission_fails_safely(ocr):
    """Reports that it read nothing, and declines to score it.

    An earlier version of this test asserted `score >= 0`, which quietly accepted a
    score of 100.0 for a submission with no images. Verdict behaviour on unreadable
    input is covered properly in test_unreadable_input.py.
    """
    outcome = run_scan([])
    assert outcome.compliance_score is None
    assert any("No text" in n for n in outcome.notes)
