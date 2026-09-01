"""Feature 6 — the scheduled auto-deletion job.

`test_api_retention.py` proves `eligible_scan_ids` (the query) cannot widen by
accident. This file proves the job that consumes it:

  * `run_auto_deletion` soft-deletes *exactly* the eligible subset and nothing else,
  * every removal is audit-logged as automated (actor None, automated=True, the
    "retention window elapsed" reason, and the retention state at the moment),
  * running it again removes nothing and writes nothing,
  * `case_open` True and `case_open` None are untouchable at any age,
  * a shorter administrator window widens what the next run removes,
  * the in-process scheduler sweeps repeatedly and survives a failing sweep.

The state matrix is built explicitly, and the assertions are on the exact id set —
a count would pass if the job deleted the wrong scan and spared a right one.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.core.db import utcnow
from app.models.enums import Role
from app.models.tables import AuditLog, Scan, User
from app.pipeline import engine_ocr
from app.services import retention, retention_scheduler
from tests.authfixtures import ADMIN_PASSWORD, API, auth, build_app, seed_user, token_for
from tests.test_api_scan import COMPLIANT_LINES, ScriptedEngine, png

OFFICER_EMAIL = "officer@metrology.gov.in"
ADMIN_EMAIL = "controller@metrology.gov.in"
WINDOW = settings.retention_days  # 30 by default


@pytest.fixture
def bench(tmp_path, monkeypatch):
    client, Session = build_app(tmp_path, monkeypatch)
    seed_user(Session, email=OFFICER_EMAIL, password=ADMIN_PASSWORD, role=Role.SENIOR_OFFICER)
    seed_user(Session, email=ADMIN_EMAIL, password=ADMIN_PASSWORD, role=Role.ADMIN)
    previous = engine_ocr._engine
    engine_ocr.set_engine(ScriptedEngine(COMPLIANT_LINES))
    with client:
        client.headers.update(auth(token_for(client, OFFICER_EMAIL, ADMIN_PASSWORD)))
        yield client, Session
    engine_ocr._engine = previous


def file_scan(client, name: str) -> str:
    r = client.post(
        f"{API}/scans",
        files=[("images", ("f.png", png(), "image/png"))],
        data={"product_name": name},
    )
    assert r.status_code == 201, r.text
    return r.json()["scan_id"]


def set_scan(Session, scan_id: str, **columns) -> None:
    db = Session()
    try:
        scan = db.get(Scan, scan_id)
        for key, value in columns.items():
            setattr(scan, key, value)
        db.commit()
    finally:
        db.close()


def scalar(Session, scan_id: str, column: str):
    db = Session()
    try:
        return getattr(db.get(Scan, scan_id), column)
    finally:
        db.close()


def deletion_entries(Session, scan_id: str) -> list[AuditLog]:
    db = Session()
    try:
        return list(
            db.execute(
                select(AuditLog).where(
                    AuditLog.entity_type == "scan",
                    AuditLog.entity_id == scan_id,
                    AuditLog.action == "SCAN_DELETED",
                )
            ).scalars()
        )
    finally:
        db.close()


# --------------------------------------------------------------- the job


def _build_matrix(client, Session) -> dict[str, str]:
    """Seven scans, one per state the job must distinguish. Returns name -> id."""
    ids = {
        name: file_scan(client, name)
        for name in (
            "undecided_ancient",
            "open_ancient",
            "closed_recent",
            "closed_under_window",
            "closed_just_over",
            "closed_ancient",
            "already_deleted",
        )
    }
    ancient = utcnow() - timedelta(days=400)

    # No answer, aged well past any window -> never eligible.
    set_scan(Session, ids["undecided_ancient"], created_at=ancient, scan_date=ancient.date())
    # A case is open, decided long ago -> never eligible.
    set_scan(Session, ids["open_ancient"], case_open=True, case_open_decided_at=ancient)
    # Closed three days ago -> not yet eligible.
    set_scan(
        Session,
        ids["closed_recent"],
        case_open=False,
        case_open_decided_at=utcnow() - timedelta(days=3),
    )
    # Closed one day inside the window -> not yet eligible.
    set_scan(
        Session,
        ids["closed_under_window"],
        case_open=False,
        case_open_decided_at=utcnow() - timedelta(days=WINDOW - 1),
    )
    # Closed one hour past the window -> eligible.
    set_scan(
        Session,
        ids["closed_just_over"],
        case_open=False,
        case_open_decided_at=utcnow() - timedelta(days=WINDOW, hours=1),
    )
    # Closed long ago -> eligible.
    set_scan(
        Session, ids["closed_ancient"], case_open=False, case_open_decided_at=ancient
    )
    # Eligible on paper but already soft-deleted -> skipped, not re-logged.
    set_scan(
        Session,
        ids["already_deleted"],
        case_open=False,
        case_open_decided_at=ancient,
        deleted_at=utcnow() - timedelta(days=1),
    )
    return ids


def test_run_auto_deletion_removes_exactly_the_eligible_subset(bench):
    client, Session = bench
    ids = _build_matrix(client, Session)

    db = Session()
    try:
        removed = set(retention.run_auto_deletion(db))
    finally:
        db.close()

    assert removed == {ids["closed_just_over"], ids["closed_ancient"]}

    # The two that were removed carry an automated soft-delete.
    for name in ("closed_just_over", "closed_ancient"):
        assert scalar(Session, ids[name], "deleted_at") is not None
        assert scalar(Session, ids[name], "deleted_by_id") is None
        assert scalar(Session, ids[name], "deleted_reason") == "retention window elapsed"

    # Everything else is untouched (the already-deleted one keeps its original stamp).
    for name in ("undecided_ancient", "open_ancient", "closed_recent", "closed_under_window"):
        assert scalar(Session, ids[name], "deleted_at") is None


def test_each_auto_deletion_is_audit_logged_as_automated(bench):
    client, Session = bench
    ids = _build_matrix(client, Session)

    db = Session()
    try:
        removed = retention.run_auto_deletion(db)
    finally:
        db.close()

    for scan_id in removed:
        entries = deletion_entries(Session, scan_id)
        assert len(entries) == 1, f"{scan_id}: expected one SCAN_DELETED entry"
        entry = entries[0]
        assert entry.actor_id is None
        assert entry.before == {"deleted_at": None}
        assert entry.after["automated"] is True
        assert entry.after["reason"] == "retention window elapsed"
        # The retention state at the instant of deletion is in the record.
        assert entry.after["case_open"] is False
        assert entry.after["case_open_decided_at"] is not None
        assert entry.after["deleted_at"] is not None

    # The already-deleted scan was not re-logged by this run.
    assert deletion_entries(Session, ids["already_deleted"]) == []


def test_run_auto_deletion_is_idempotent(bench):
    client, Session = bench
    _build_matrix(client, Session)

    db = Session()
    try:
        first = retention.run_auto_deletion(db)
        assert first, "sanity: the first run should remove something"
        before = db.execute(
            select(AuditLog).where(AuditLog.action == "SCAN_DELETED")
        ).scalars().all()

        second = retention.run_auto_deletion(db)
        after = db.execute(
            select(AuditLog).where(AuditLog.action == "SCAN_DELETED")
        ).scalars().all()
    finally:
        db.close()

    assert second == []
    assert len(after) == len(before), "a second run must not write new deletions"


def test_case_open_true_is_never_auto_deleted_at_any_age(bench):
    client, Session = bench
    scan_id = file_scan(client, "open-forever")
    set_scan(
        Session,
        scan_id,
        case_open=True,
        case_open_decided_at=utcnow() - timedelta(days=3650),
    )
    db = Session()
    try:
        assert retention.run_auto_deletion(db) == []
    finally:
        db.close()
    assert scalar(Session, scan_id, "deleted_at") is None


def test_an_unanswered_scan_is_never_auto_deleted_at_any_age(bench):
    client, Session = bench
    scan_id = file_scan(client, "never-reviewed")
    old = utcnow() - timedelta(days=3650)
    set_scan(Session, scan_id, created_at=old, scan_date=old.date())  # case_open stays None
    db = Session()
    try:
        assert retention.run_auto_deletion(db) == []
    finally:
        db.close()
    assert scalar(Session, scan_id, "deleted_at") is None


def test_a_shorter_admin_window_widens_what_the_next_run_removes(bench):
    client, Session = bench
    scan_id = file_scan(client, "closed-eight-days")
    set_scan(
        Session,
        scan_id,
        case_open=False,
        case_open_decided_at=utcnow() - timedelta(days=8),
    )

    db = Session()
    try:
        # Default 30-day window: eight days is not enough.
        assert retention.run_auto_deletion(db) == []

        admin_user = db.execute(
            select(User).where(User.email == ADMIN_EMAIL)
        ).scalars().one()
        retention.set_retention_days(db, 7, admin_user)
        db.commit()

        # Now eight days is past the window.
        assert retention.run_auto_deletion(db) == [scan_id]
    finally:
        db.close()
    assert scalar(Session, scan_id, "deleted_reason") == "retention window elapsed"


# ----------------------------------------------------------- the scheduler


def test_the_scheduler_sweeps_repeatedly_until_stopped(monkeypatch):
    calls = 0

    def counting_sweep() -> list[str]:
        nonlocal calls
        calls += 1
        return []

    monkeypatch.setattr(retention_scheduler, "_sweep_once", counting_sweep)

    async def drive() -> None:
        stop = asyncio.Event()
        task = asyncio.create_task(
            retention_scheduler.run_periodically(
                interval_seconds=0.02, initial_delay_seconds=0.0, stop=stop
            )
        )
        await asyncio.sleep(0.12)
        stop.set()
        await task

    asyncio.run(drive())
    assert calls >= 3, f"expected several sweeps, got {calls}"


def test_the_scheduler_survives_a_failing_sweep(monkeypatch):
    calls = 0

    def flaky_sweep() -> list[str]:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("database temporarily unreachable")
        return []

    monkeypatch.setattr(retention_scheduler, "_sweep_once", flaky_sweep)

    async def drive() -> None:
        stop = asyncio.Event()
        task = asyncio.create_task(
            retention_scheduler.run_periodically(
                interval_seconds=0.02, initial_delay_seconds=0.0, stop=stop
            )
        )
        await asyncio.sleep(0.1)
        stop.set()
        await task  # must not raise — the failed sweep was swallowed

    asyncio.run(drive())
    assert calls >= 2, "the loop should have kept sweeping after the failure"


def test_the_initial_delay_can_be_interrupted_before_the_first_sweep(monkeypatch):
    calls = 0

    def counting_sweep() -> list[str]:
        nonlocal calls
        calls += 1
        return []

    monkeypatch.setattr(retention_scheduler, "_sweep_once", counting_sweep)

    async def drive() -> None:
        stop = asyncio.Event()
        task = asyncio.create_task(
            retention_scheduler.run_periodically(
                interval_seconds=10, initial_delay_seconds=10, stop=stop
            )
        )
        await asyncio.sleep(0.02)
        stop.set()
        await asyncio.wait_for(task, timeout=1.0)  # returns promptly, no sweep

    asyncio.run(drive())
    assert calls == 0
