"""The officer retention decision.

The rule, restated so the tests can be read against it:

  * The officer answers one explicit question: is a case still open on this scan?
  * YES  -> never auto-deleted, at any age.
  * NO   -> eligible for auto-deletion once the window has passed *from the answer*,
           not from when the scan was filed.
  * No answer yet -> never eligible. Silence is not consent to delete.
  * The verdict does not matter. A COMPLIANT scan the officer flags case_open = true
    is retained the same as any other.
  * Changing the answer is audit-logged with the old value and the new one, and
    restarts the clock.

`eligible_scan_ids` is the query the auto-delete job (Feature 6) will run. Testing it
exhaustively here means the job cannot widen it by accident later.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.core.config import settings
from app.core.db import utcnow
from app.models.enums import Role, Verdict
from app.models.tables import Scan
from app.pipeline import engine_ocr
from app.services import retention
from tests.authfixtures import (
    ADMIN_PASSWORD,
    API,
    OFFICER_PASSWORD,
    auth,
    build_app,
    seed_user,
    token_for,
)
from tests.test_api_scan import COMPLIANT_LINES, ScriptedEngine, png

OFFICER_EMAIL = "officer@metrology.gov.in"
OTHER_EMAIL = "other.officer@metrology.gov.in"
ADMIN_EMAIL = "controller@metrology.gov.in"

WINDOW = settings.retention_days  # 30 by default


@pytest.fixture
def bench(tmp_path, monkeypatch):
    client, Session = build_app(tmp_path, monkeypatch)
    seed_user(Session, email=OFFICER_EMAIL, password=OFFICER_PASSWORD, role=Role.SENIOR_OFFICER)
    seed_user(Session, email=OTHER_EMAIL, password=OFFICER_PASSWORD, role=Role.SENIOR_OFFICER)
    seed_user(Session, email=ADMIN_EMAIL, password=ADMIN_PASSWORD, role=Role.ADMIN)

    previous = engine_ocr._engine
    engine_ocr.set_engine(ScriptedEngine(COMPLIANT_LINES))
    with client:
        client.headers.update(auth(token_for(client, OFFICER_EMAIL, OFFICER_PASSWORD)))
        yield client, Session
    engine_ocr._engine = previous


def file_scan(client, name="Roasted Chana Masala"):
    r = client.post(
        f"{API}/scans",
        files=[("images", ("f.png", png(), "image/png"))],
        data={"product_name": name},
    )
    assert r.status_code == 201, r.text
    return r.json()


def set_scan(Session, scan_id, **columns):
    """Reach past the API to age a scan or set its verdict for a test."""
    db = Session()
    try:
        scan = db.get(Scan, scan_id)
        for key, value in columns.items():
            setattr(scan, key, value)
        db.commit()
    finally:
        db.close()


# --------------------------------------------------------------- the decision


def test_a_fresh_scan_has_no_retention_answer_and_is_not_eligible(bench):
    client, _ = bench
    scan = file_scan(client)
    assert scan["retention"]["case_open"] is None
    assert scan["retention"]["eligible_for_deletion"] is False
    assert "not yet reviewed" in scan["retention"]["summary"].lower()


def test_answering_yes_keeps_the_scan_and_never_makes_it_eligible(bench):
    client, Session = bench
    scan = file_scan(client)

    body = client.post(
        f"{API}/scans/{scan['scan_id']}/retention", json={"case_open": True}
    ).json()
    assert body["retention"]["case_open"] is True
    assert body["retention"]["decided_at"]
    assert body["retention"]["decided_by_id"]
    assert body["retention"]["eligible_for_deletion"] is False
    assert body["retention"]["eligible_on"] is None

    # Age it well past any window. Still not eligible.
    set_scan(
        Session,
        scan["scan_id"],
        case_open_decided_at=utcnow() - timedelta(days=365),
    )
    reopened = client.get(f"{API}/scans/{scan['scan_id']}").json()
    assert reopened["retention"]["eligible_for_deletion"] is False


def test_answering_no_starts_the_clock_from_the_answer_not_the_scan_date(bench):
    """A scan filed 25 days ago and marked case-closed today has a full window left."""
    client, Session = bench
    scan = file_scan(client)
    set_scan(
        Session,
        scan["scan_id"],
        scan_date=(utcnow() - timedelta(days=25)).date(),
        created_at=utcnow() - timedelta(days=25),
    )

    body = client.post(
        f"{API}/scans/{scan['scan_id']}/retention", json={"case_open": False}
    ).json()
    assert body["retention"]["case_open"] is False
    assert body["retention"]["eligible_for_deletion"] is False

    eligible_on = body["retention"]["eligible_on"]
    # ~30 days from *now*, not ~5 days from the scan date.
    days_out = (
        __import__("datetime").datetime.fromisoformat(eligible_on).date() - utcnow().date()
    ).days
    assert WINDOW - 1 <= days_out <= WINDOW + 1


def test_a_closed_scan_becomes_eligible_once_the_window_elapses(bench):
    client, Session = bench
    scan = file_scan(client)
    client.post(f"{API}/scans/{scan['scan_id']}/retention", json={"case_open": False})

    set_scan(
        Session,
        scan["scan_id"],
        case_open_decided_at=utcnow() - timedelta(days=WINDOW + 1),
    )
    body = client.get(f"{API}/scans/{scan['scan_id']}").json()
    assert body["retention"]["eligible_for_deletion"] is True
    assert "eligible for auto-deletion" in body["retention"]["summary"].lower()


def test_changing_the_answer_restarts_the_clock(bench):
    """Close, then reopen, then close again a month later -> a fresh window from the
    second close, not the first."""
    client, Session = bench
    scan = file_scan(client)

    client.post(f"{API}/scans/{scan['scan_id']}/retention", json={"case_open": False})
    set_scan(
        Session,
        scan["scan_id"],
        case_open_decided_at=utcnow() - timedelta(days=WINDOW + 5),
    )
    assert client.get(f"{API}/scans/{scan['scan_id']}").json()["retention"][
        "eligible_for_deletion"
    ] is True

    # Officer reopens, then closes again.
    client.post(f"{API}/scans/{scan['scan_id']}/retention", json={"case_open": True})
    client.post(f"{API}/scans/{scan['scan_id']}/retention", json={"case_open": False})

    after = client.get(f"{API}/scans/{scan['scan_id']}").json()
    assert after["retention"]["eligible_for_deletion"] is False


def test_a_compliant_verdict_does_not_make_a_scan_deletable_on_its_own(bench):
    """The invariant the spec calls out. Verdict never governs deletion; the answer
    does."""
    client, Session = bench
    scan = file_scan(client)
    set_scan(Session, scan["scan_id"], verdict=Verdict.COMPLIANT)

    # No answer yet: not eligible, whatever the verdict, whatever the age.
    set_scan(
        Session,
        scan["scan_id"],
        created_at=utcnow() - timedelta(days=400),
        scan_date=(utcnow() - timedelta(days=400)).date(),
    )
    assert client.get(f"{API}/scans/{scan['scan_id']}").json()["retention"][
        "eligible_for_deletion"
    ] is False

    # Officer says a case is open on this compliant scan (a repeat-inspection
    # baseline). Retained the same as any other.
    client.post(f"{API}/scans/{scan['scan_id']}/retention", json={"case_open": True})
    set_scan(Session, scan["scan_id"], case_open_decided_at=utcnow() - timedelta(days=400))
    assert client.get(f"{API}/scans/{scan['scan_id']}").json()["retention"][
        "eligible_for_deletion"
    ] is False


# ------------------------------------------------ the query the job will run


def test_eligible_scan_ids_returns_only_closed_scans_past_the_window(bench):
    """Impossible to pass by accident: one scan in each of the four states, plus a
    boundary case, and only the closed+old one comes back."""
    client, Session = bench

    ids: dict[str, str] = {}
    for name in ("undecided", "open_old", "closed_recent", "closed_old", "closed_boundary"):
        ids[name] = file_scan(client, name=name)["scan_id"]

    old = utcnow() - timedelta(days=WINDOW + 10)
    recent = utcnow() - timedelta(days=3)
    boundary = utcnow() - timedelta(days=WINDOW, hours=1)

    # undecided: no answer, aged well past the window. Must NOT be eligible.
    set_scan(Session, ids["undecided"], created_at=old, scan_date=old.date())

    # open_old: case_open = True, decided long ago. Must NOT be eligible, ever.
    set_scan(Session, ids["open_old"], case_open=True, case_open_decided_at=old)

    # closed_recent: case_open = False, decided 3 days ago. Not yet eligible.
    set_scan(Session, ids["closed_recent"], case_open=False, case_open_decided_at=recent)

    # closed_old: case_open = False, decided past the window. THE ONLY eligible one.
    set_scan(Session, ids["closed_old"], case_open=False, case_open_decided_at=old)

    # closed_boundary: just over the window. Eligible.
    set_scan(
        Session, ids["closed_boundary"], case_open=False, case_open_decided_at=boundary
    )

    db = Session()
    try:
        eligible = set(retention.eligible_scan_ids(db))
    finally:
        db.close()

    assert ids["closed_old"] in eligible
    assert ids["closed_boundary"] in eligible
    assert ids["undecided"] not in eligible
    assert ids["open_old"] not in eligible
    assert ids["closed_recent"] not in eligible
    assert eligible == {ids["closed_old"], ids["closed_boundary"]}


def test_eligible_scan_ids_ignores_already_deleted_scans(bench):
    client, Session = bench
    scan = file_scan(client)
    set_scan(
        Session,
        scan["scan_id"],
        case_open=False,
        case_open_decided_at=utcnow() - timedelta(days=WINDOW + 30),
        deleted_at=utcnow() - timedelta(days=1),
    )
    db = Session()
    try:
        assert scan["scan_id"] not in set(retention.eligible_scan_ids(db))
    finally:
        db.close()


# ------------------------------------------------------------------- audit log


def test_the_decision_is_audit_logged_with_the_previous_answer(bench):
    client, _ = bench
    scan = file_scan(client)

    client.post(f"{API}/scans/{scan['scan_id']}/retention", json={"case_open": False})
    client.post(f"{API}/scans/{scan['scan_id']}/retention", json={"case_open": True})

    entries = client.get(
        f"{API}/auth/audit", params={"entity_type": "scan", "entity_id": scan["scan_id"]}
    ).json()
    decisions = [e for e in entries if e["action"] == "RETENTION_DECISION"]
    assert len(decisions) == 2

    # Newest first: the True decision records the previous False.
    assert decisions[0]["after"]["case_open"] is True
    assert decisions[0]["before"]["case_open"] is False
    assert decisions[0]["actor_email"] == OFFICER_EMAIL
    # The first decision records the previous None.
    assert decisions[1]["before"]["case_open"] is None
    assert decisions[1]["after"]["case_open"] is False


# ---------------------------------------------------------------- permissions


def test_the_retention_endpoint_needs_an_officer(bench):
    client, _ = bench
    scan = file_scan(client)
    r = client.post(
        f"{API}/scans/{scan['scan_id']}/retention",
        json={"case_open": True},
        headers={"Authorization": ""},
    )
    assert r.status_code == 401


def test_any_officer_can_record_a_retention_decision(bench):
    """Retention is a case-management judgement, not evidence — any officer may make
    it, not only the one who filed the scan."""
    client, _ = bench
    scan = file_scan(client)
    other = auth(token_for(client, OTHER_EMAIL, OFFICER_PASSWORD))
    r = client.post(
        f"{API}/scans/{scan['scan_id']}/retention", json={"case_open": True}, headers=other
    )
    assert r.status_code == 200
    assert r.json()["retention"]["case_open"] is True


def test_a_missing_body_is_rejected(bench):
    client, _ = bench
    scan = file_scan(client)
    assert client.post(f"{API}/scans/{scan['scan_id']}/retention", json={}).status_code == 422


def test_recording_retention_on_an_unknown_scan_is_a_404(bench):
    client, _ = bench
    assert (
        client.post(f"{API}/scans/{'0' * 32}/retention", json={"case_open": True}).status_code
        == 404
    )


# --------------------------------------------------- the listing surfaces it


def test_the_repository_listing_shows_the_retention_answer(bench):
    client, Session = bench
    scan = file_scan(client, name="Listed pack")
    client.post(f"{API}/scans/{scan['scan_id']}/retention", json={"case_open": False})
    set_scan(
        Session,
        scan["scan_id"],
        case_open_decided_at=utcnow() - timedelta(days=WINDOW + 2),
    )

    page = client.get(f"{API}/scans", params={"product_id": scan["product_id"]}).json()
    row = next(s for s in page["scans"] if s["scan_id"] == scan["scan_id"])
    assert row["case_open"] is False
    assert row["eligible_for_deletion"] is True
