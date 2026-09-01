"""Scoring coverage, and which ruleset judges a scan.

The class of bug these cover: a number that is arithmetically right and materially
misleading. "100%" computed over the two rules a scan managed to decide reads as a
clean bill of health; a 2015 pack judged against 2022 rules is condemned for omitting
a declaration that did not exist when it was packed.
"""

from __future__ import annotations

import logging
from datetime import date

import pytest
from conftest import compliant_context, field

from app.models.enums import Channel, FindingStatus, Verdict
from app.rules.engine import coverage, evaluate, score, verdict
from app.rules.loader import ruleset_for_date
from app.rules.schema import ScanContext

# ------------------------------------------------------------------- coverage


def test_a_full_scan_decides_most_of_the_applicable_rules(ruleset):
    findings, _ = evaluate(compliant_context(), ruleset)
    decided, applicable = coverage(findings)
    assert decided >= 10
    assert decided <= applicable


def test_coverage_excludes_rules_that_did_not_apply(ruleset):
    """An e-commerce listing has the geometry rules marked NA, not undecided."""
    findings, _ = evaluate(compliant_context(channel=Channel.ECOMMERCE), ruleset)
    _, applicable = coverage(findings)
    na = sum(1 for f in findings if f.status is FindingStatus.NA)
    assert applicable == len(findings) - na


def test_a_barely_read_pack_reports_low_coverage_beside_its_score(ruleset):
    """The case that makes coverage necessary: 100% over almost nothing.

    A 8 g sachet is exempt from most declarations under Rule 26(a), and this scan read
    only its net quantity. The two rules it can decide both pass, so the score is
    100.0 — which must never be shown without the coverage that qualifies it.
    """
    ctx = ScanContext(
        fields={"net_quantity": field("net_quantity", "8 g", value=8, unit="g")},
        blocks_read=1,
        category="FOOD",
    )
    findings, exemption = evaluate(ctx, ruleset)
    decided, applicable = coverage(findings)

    assert exemption is not None and exemption.id == "SMALL_PACKAGE"
    assert score(findings) == 100.0
    assert decided <= 3, "expected almost nothing to be decided"
    assert verdict(findings, score(findings)) is Verdict.INCONCLUSIVE


def test_nothing_decided_means_no_score_and_zero_coverage(ruleset):
    findings, _ = evaluate(ScanContext(fields={}, blocks_read=0), ruleset)
    decided, _ = coverage(findings)
    assert decided == 0
    assert score(findings) is None


def test_coverage_rises_as_more_of_the_label_is_read(ruleset):
    thin = ScanContext(
        fields={"mrp": field("mrp", "MRP Rs. 45.00 inclusive of all taxes",
                             amount=45.0, all_amounts=[45.0])},
        blocks_read=4,
    )
    full = compliant_context()
    assert coverage(evaluate(thin, ruleset)[0])[0] < coverage(evaluate(full, ruleset)[0])[0]


# --------------------------------------------------------------- rule dating


def test_the_ruleset_in_force_is_chosen_by_scan_date():
    assert ruleset_for_date(date(2022, 4, 1)).version == "2022-04-01"
    assert ruleset_for_date(date(2026, 8, 29)).version == "2022-04-01"


def test_a_scan_predating_every_ruleset_is_flagged_not_silently_judged(caplog):
    """Rule 6(11) took effect in 2022. A 2015 pack must not be condemned for it
    without the mismatch being recorded."""
    with caplog.at_level(logging.WARNING, logger="app.rules.loader"):
        chosen = ruleset_for_date(date(2015, 6, 1))
    assert chosen is not None
    assert any("No ruleset was in force" in r.message for r in caplog.records), (
        "a scan judged by rules that post-date it left no warning"
    )


def test_the_warning_names_the_dates_involved(caplog):
    with caplog.at_level(logging.WARNING, logger="app.rules.loader"):
        ruleset_for_date(date(2015, 6, 1))
    text = " ".join(r.getMessage() for r in caplog.records)
    assert "2015-06-01" in text and "2022-04-01" in text


def test_a_current_scan_produces_no_dating_warning(caplog):
    with caplog.at_level(logging.WARNING, logger="app.rules.loader"):
        ruleset_for_date(date(2026, 8, 29))
    assert [r for r in caplog.records if "No ruleset was in force" in r.message] == []


def test_findings_cite_the_ruleset_that_judged_them(ruleset):
    """Every report must be reproducible against a named version."""
    assert ruleset.version == "2022-04-01"
    assert ruleset.effective_date == date(2022, 4, 1)


@pytest.mark.slow
def test_the_runner_records_coverage():
    pytest.importorskip("cv2")
    from app.pipeline import synth
    from app.pipeline.runner import ScanInput, run_scan

    outcome = run_scan([ScanInput(image=synth.render(synth.compliant_label()), image_id="img1")])
    decided, applicable = outcome.coverage
    assert 0 < decided <= applicable
    assert decided >= 10
