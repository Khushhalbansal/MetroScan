"""What the system may claim when it cannot read the label.

The class of bug these cover: the engine treating "I did not find this declaration"
as "this declaration is not on the package". Those are different claims, and only the
second is a violation. A dark frame, a blurred capture, a shot of the wrong panel or
an empty submission all produce no declarations — and none of them are evidence that
a product is non-compliant.

A wrong verdict is worse than a crash here, because a compliance report is meant to be
attachable to an enforcement action.
"""

from __future__ import annotations

import numpy as np
import pytest
from conftest import compliant_context, field

from app.models.enums import Channel, FindingStatus, Verdict
from app.rules.engine import evaluate, score, verdict
from app.rules.schema import (
    MIN_BLOCKS_TO_ASSERT_ABSENCE,
    MIN_OCR_CONFIDENCE_TO_ASSERT_ABSENCE,
    ScanContext,
)

PRESENCE_RULES = [
    "MANUFACTURER_NAME_PRESENT",
    "MANUFACTURER_ADDRESS_PRESENT",
    "COMMON_NAME_PRESENT",
    "NET_QUANTITY_PRESENT",
    "MFG_DATE_PRESENT",
    "MRP_PRESENT",
    "CONSUMER_CARE_PRESENT",
]


def judge(ctx: ScanContext, ruleset) -> dict[str, FindingStatus]:
    findings, _ = evaluate(ctx, ruleset)
    return {f.rule_id: f.status for f in findings}


# ------------------------------------------------------- nothing was read at all


@pytest.fixture
def read_nothing() -> ScanContext:
    """What the pipeline hands the engine after a lens-cap photograph."""
    return ScanContext(channel=Channel.PHYSICAL, fields={}, blocks_read=0)


def test_an_unread_label_asserts_no_violations(read_nothing, ruleset):
    statuses = judge(read_nothing, ruleset)
    invented = [r for r in PRESENCE_RULES if statuses[r] is FindingStatus.FAIL]
    assert invented == [], f"claimed violations on a label it never read: {invented}"


def test_an_unread_label_is_sent_for_review(read_nothing, ruleset):
    statuses = judge(read_nothing, ruleset)
    assert all(statuses[r] is FindingStatus.NEEDS_REVIEW for r in PRESENCE_RULES)


def test_an_unread_label_explains_itself_to_the_officer(read_nothing, ruleset):
    findings, _ = evaluate(read_nothing, ruleset)
    message = next(f.message for f in findings if f.rule_id == "MRP_PRESENT")
    assert "could not be read" in message
    assert "Re-photograph" in message


def test_an_unread_label_has_no_score_rather_than_a_zero(read_nothing, ruleset):
    """A zero is a judgement about the product; "not assessed" is not."""
    findings, _ = evaluate(read_nothing, ruleset)
    assert score(findings) is None


def test_an_unread_label_is_inconclusive_not_non_compliant(read_nothing, ruleset):
    findings, _ = evaluate(read_nothing, ruleset)
    assert verdict(findings, score(findings)) is Verdict.INCONCLUSIVE


# --------------------------------------------------- barely read / wrong panel


def test_a_couple_of_stray_blocks_still_cannot_prove_absence(ruleset):
    """Two smudges of recovered text are not a reading of the label."""
    ctx = ScanContext(channel=Channel.PHYSICAL, fields={}, blocks_read=2)
    statuses = judge(ctx, ruleset)
    assert all(statuses[r] is FindingStatus.NEEDS_REVIEW for r in PRESENCE_RULES)


def test_text_without_any_recognised_declaration_cannot_prove_absence(ruleset):
    """A photograph of the ingredients panel reads plenty of text and no declarations."""
    ctx = ScanContext(channel=Channel.PHYSICAL, fields={}, blocks_read=25)
    assert judge(ctx, ruleset)["MRP_PRESENT"] is FindingStatus.NEEDS_REVIEW


def test_a_genuinely_read_label_can_still_be_found_non_compliant(ruleset):
    """The guard must not become a blanket excuse — real violations still fail."""
    ctx = compliant_context()
    ctx.blocks_read = 20
    del ctx.fields["mrp"]
    statuses = judge(ctx, ruleset)
    assert statuses["MRP_PRESENT"] is FindingStatus.FAIL
    findings, _ = evaluate(ctx, ruleset)
    assert verdict(findings, score(findings)) is Verdict.NON_COMPLIANT


def test_a_sparse_but_real_label_can_assert_absence(ruleset):
    """One declaration found plus enough text read is sufficient to judge the rest."""
    ctx = ScanContext(
        channel=Channel.PHYSICAL,
        fields={"mrp": field("mrp", "MRP Rs. 45.00 inclusive of all taxes",
                             amount=45.0, all_amounts=[45.0])},
        blocks_read=MIN_BLOCKS_TO_ASSERT_ABSENCE,
    )
    assert judge(ctx, ruleset)["NET_QUANTITY_PRESENT"] is FindingStatus.FAIL


def test_the_absence_threshold_is_the_documented_one(ruleset):
    """Directly pins the boundary, so moving it is a deliberate act."""
    below = ScanContext(
        fields={"mrp": field("mrp", "MRP Rs. 45.00")},
        blocks_read=MIN_BLOCKS_TO_ASSERT_ABSENCE - 1,
    )
    at = ScanContext(
        fields={"mrp": field("mrp", "MRP Rs. 45.00")},
        blocks_read=MIN_BLOCKS_TO_ASSERT_ABSENCE,
    )
    assert below.can_assert_absence is False
    assert at.can_assert_absence is True


def test_a_low_confidence_read_cannot_prove_absence(ruleset):
    """Block count is not enough. Eight blocks of motion-blurred guesswork clear the
    count but do not amount to a reading of the label, so 'this declaration is not on
    the pack' is still not a claim this scan can make."""
    ctx = ScanContext(
        channel=Channel.PHYSICAL,
        fields={"mrp": field("mrp", "MRP Rs. 45.00", amount=45.0, all_amounts=[45.0])},
        blocks_read=8,
        ocr_confidence=0.6,
    )
    assert ctx.can_assert_absence is False
    assert judge(ctx, ruleset)["NET_QUANTITY_PRESENT"] is FindingStatus.NEEDS_REVIEW


def test_a_confident_sparse_read_still_asserts_absence(ruleset):
    """The gate is confidence, not perfection: three blocks read clearly are enough."""
    ctx = ScanContext(
        channel=Channel.PHYSICAL,
        fields={"mrp": field("mrp", "MRP Rs. 45.00", amount=45.0, all_amounts=[45.0])},
        blocks_read=MIN_BLOCKS_TO_ASSERT_ABSENCE,
        ocr_confidence=0.95,
    )
    assert ctx.can_assert_absence is True
    assert judge(ctx, ruleset)["NET_QUANTITY_PRESENT"] is FindingStatus.FAIL


def test_the_ocr_confidence_floor_is_the_documented_one(ruleset):
    """Pins the second boundary, so moving it is also a deliberate act."""
    common = {"fields": {"mrp": field("mrp", "MRP Rs. 45.00")}, "blocks_read": 8}
    below = ScanContext(**common, ocr_confidence=MIN_OCR_CONFIDENCE_TO_ASSERT_ABSENCE - 0.01)
    at = ScanContext(**common, ocr_confidence=MIN_OCR_CONFIDENCE_TO_ASSERT_ABSENCE)
    assert below.can_assert_absence is False
    assert at.can_assert_absence is True


def test_consumer_care_completeness_is_not_asserted_on_an_unread_label(ruleset):
    ctx = ScanContext(channel=Channel.PHYSICAL, fields={}, blocks_read=0)
    assert judge(ctx, ruleset)["CONSUMER_CARE_COMPLETE"] is FindingStatus.NEEDS_REVIEW


def test_ecommerce_listing_that_could_not_be_read_is_not_condemned(ruleset):
    ctx = ScanContext(channel=Channel.ECOMMERCE, fields={}, blocks_read=0)
    assert judge(ctx, ruleset)["ECOMMERCE_DECLARATIONS_DISPLAYED"] is FindingStatus.NEEDS_REVIEW


def test_unit_sale_price_is_not_asserted_missing_on_an_unread_label(ruleset):
    ctx = ScanContext(channel=Channel.PHYSICAL, fields={}, blocks_read=0)
    assert judge(ctx, ruleset)["UNIT_SALE_PRICE_PRESENT"] is FindingStatus.NEEDS_REVIEW


# ------------------------------------------------------------ through the runner


@pytest.mark.slow
def test_a_dark_frame_produces_no_verdict_through_the_full_pipeline():
    pytest.importorskip("cv2")
    from app.pipeline.runner import ScanInput, run_scan

    lens_cap = np.full((800, 600, 3), 20, np.uint8)
    outcome = run_scan([ScanInput(image=lens_cap, image_id="img1")])

    assert outcome.compliance_score is None
    assert outcome.verdict is Verdict.INCONCLUSIVE
    failures = [f.rule_id for f in outcome.findings if f.status is FindingStatus.FAIL]
    assert failures == [], f"invented violations from a dark frame: {failures}"


@pytest.mark.slow
def test_an_empty_submission_produces_no_verdict():
    pytest.importorskip("cv2")
    from app.pipeline.runner import run_scan

    outcome = run_scan([])
    assert outcome.compliance_score is None
    assert outcome.verdict is Verdict.INCONCLUSIVE
    assert [f for f in outcome.findings if f.status is FindingStatus.FAIL] == []
