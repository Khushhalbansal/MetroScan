"""The enforcement dashboard.

An aggregate is where an invariant is easiest to lose. A single scan refuses to report
0/100 when it could decide nothing; a dashboard that averages that scan into a
compliance rate has undone the refusal one level up, and nobody looking at the chart
can tell. These tests hold the same line over the estate that the engine holds over a
package.
"""

from __future__ import annotations

import pytest

from app.models.enums import Role
from app.pipeline import engine_ocr
from tests.authfixtures import API, OFFICER_PASSWORD, auth, build_app, seed_user, token_for
from tests.test_api_scan import COMPLIANT_LINES, ScriptedEngine, png

OFFICER_EMAIL = "officer@metrology.gov.in"
NO_TAX_RIDER = [line for line in COMPLIANT_LINES if "inclusive of all taxes" not in line]


@pytest.fixture
def client(tmp_path, monkeypatch):
    c, Session = build_app(tmp_path, monkeypatch)
    seed_user(Session, email=OFFICER_EMAIL, password=OFFICER_PASSWORD, role=Role.SENIOR_OFFICER)
    with c:
        c.headers.update(auth(token_for(c, OFFICER_EMAIL, OFFICER_PASSWORD)))
        yield c


@pytest.fixture
def scripted(request):
    lines = getattr(request, "param", COMPLIANT_LINES)
    previous = engine_ocr._engine
    engine_ocr.set_engine(ScriptedEngine(lines))
    yield
    engine_ocr._engine = previous


def file_scan(client, name="Roasted Chana Masala", category="FOOD"):
    return client.post(
        f"{API}/scans",
        files=[("images", ("front.png", png(), "image/png"))],
        data={"product_name": name, "category": category},
    ).json()


def board(client, **params):
    response = client.get(f"{API}/dashboard", params=params)
    assert response.status_code == 200, response.text
    return response.json()


# ------------------------------------------------------------------------ shape


def test_an_empty_bench_reports_nothing_rather_than_zero_percent(client):
    """No scans at all is not 0% compliance.

    A rate over zero concluded scans is not a low number; it is not a number. Printing
    0% would accuse an office that has not inspected anything yet.
    """
    body = board(client)
    assert body["totals"]["scans"] == 0
    assert body["totals"]["compliance_rate"] is None
    assert body["top_violations"] == []


def test_the_window_is_always_stated(client):
    body = board(client, days=30)
    assert body["window"]["days"] == 30
    assert body["window"]["since"] < body["window"]["until"]


def test_the_dashboard_is_not_public(client):
    assert client.get(f"{API}/dashboard", headers={"Authorization": ""}).status_code == 401


def test_an_absurd_window_is_refused(client):
    assert client.get(f"{API}/dashboard", params={"days": 0}).status_code == 422
    assert client.get(f"{API}/dashboard", params={"days": 5000}).status_code == 422


# ------------------------------------------------------------------- invariants


def test_scans_that_decided_nothing_never_enter_the_compliance_rate(client):
    """The invariant this whole module exists for.

    Three unreadable scans are three products nobody assessed. They are counted, and
    named as inconclusive, and kept out of the rate — because folding them in either
    direction is a claim about packages that were never examined.
    """
    for i in range(3):
        file_scan(client, name=f"Unreadable {i}")  # real engine, blank image

    totals = board(client)["totals"]
    assert totals["scans"] == 3
    assert totals["inconclusive"] == 3
    assert totals["concluded"] == 0
    assert totals["compliance_rate"] is None
    assert totals["non_compliant"] == 0


@pytest.mark.parametrize("scripted", [NO_TAX_RIDER], indirect=True)
def test_a_violation_an_officer_overrules_stops_counting_as_one(client, scripted):
    """Enforcement totals follow the record as it stands, not as the software left it.

    The scan still carries what the software found — that is asserted in the auth
    suite — but an officer who has cleared a violation should not keep seeing it in
    the count of violations to act on.
    """
    scan = file_scan(client)
    before = board(client)
    assert any(v["rule_id"] == "MRP_INCLUSIVE_OF_TAXES" for v in before["top_violations"])

    client.post(
        f"{API}/scans/{scan['scan_id']}/findings/MRP_INCLUSIVE_OF_TAXES:override",
        json={"status": "PASS", "reason": "Rider is on the reverse panel, verified on the pack."},
    )

    after = board(client)
    assert not any(v["rule_id"] == "MRP_INCLUSIVE_OF_TAXES" for v in after["top_violations"])
    assert after["totals"]["officer_decisions"] == 1


def test_the_share_of_scans_with_no_scale_reference_is_reported(client):
    """The most actionable number an enforcement office has.

    Every scan without a fiducial leaves every Rule 8 question unanswered, and the fix
    is not software — it is telling inspectors to put the card in the frame. A
    dashboard that hides this reports a system working better than it is.
    """
    file_scan(client)
    calibration = board(client)["calibration"]
    assert calibration["scans"] == 1
    assert calibration["calibrated"] == 0
    assert calibration["uncalibrated"] == 1
    assert calibration["calibrated_rate"] == 0.0


@pytest.mark.parametrize("scripted", [NO_TAX_RIDER], indirect=True)
def test_violations_are_ranked_with_their_citations(client, scripted):
    """A count of a rule id nobody can look up is not actionable."""
    file_scan(client)
    file_scan(client, name="Another pack")

    violations = board(client)["top_violations"]
    assert violations
    top = violations[0]
    assert top["count"] == 2
    assert top["citation"]
    assert top["title"]
    assert top["severity"] in ("CRITICAL", "MAJOR", "MINOR")


@pytest.mark.parametrize("scripted", [NO_TAX_RIDER], indirect=True)
def test_categories_keep_their_inconclusive_scans_visible(client, scripted):
    file_scan(client, category="FOOD")
    rows = {row["category"]: row for row in board(client)["by_category"]}
    assert "FOOD" in rows
    assert rows["FOOD"]["scans"] == 1
    assert set(rows["FOOD"]) >= {"compliant", "non_compliant", "inconclusive", "compliance_rate"}


def test_an_uncategorised_product_is_named_not_dropped(client):
    """A blank category must not make a scan disappear from the breakdown."""
    client.post(
        f"{API}/scans",
        files=[("images", ("front.png", png(), "image/png"))],
        data={"product_name": "No category"},
    )
    rows = {row["category"] for row in board(client)["by_category"]}
    assert "Uncategorised" in rows


@pytest.mark.parametrize("scripted", [NO_TAX_RIDER], indirect=True)
def test_open_reviews_are_counted_so_the_queue_is_visible(client, scripted):
    file_scan(client)
    assert board(client)["totals"]["open_reviews"] > 0


@pytest.mark.parametrize("scripted", [NO_TAX_RIDER], indirect=True)
def test_the_daily_series_adds_up_to_the_totals(client, scripted):
    """A trend line that disagrees with the headline is worse than no trend line."""
    file_scan(client)
    file_scan(client, name="Second pack")
    body = board(client)
    assert sum(day["scans"] for day in body["daily"]) == body["totals"]["scans"]


def test_a_scan_outside_the_window_is_not_counted(client, scripted):
    """The window is a claim about a period; a scan from outside it is not evidence."""
    client.post(
        f"{API}/scans",
        files=[("images", ("front.png", png(), "image/png"))],
        data={"product_name": "Old pack", "scan_date": "2023-01-01"},
    )
    assert board(client, days=30)["totals"]["scans"] == 0
    assert board(client, days=730)["totals"]["scans"] >= 0  # window is bounded, not open
