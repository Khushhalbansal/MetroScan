"""The retention decision and its consequences.

One question governs whether a scan is ever auto-deleted: has the officer said a case
is still open on it? Not the verdict, not the age, not whether anyone has looked at it
recently — that one explicit answer.

    case_open is None   the officer has not answered. Never eligible. Silence is not
                        consent to delete.
    case_open is True    a case is open. Never auto-deleted, at any age. Only a manual
                        delete by an authorised role can remove it.
    case_open is False   no case is open. Eligible once `retention_days` have passed
                        *since case_open_decided_at* — the clock starts at the answer,
                        not at scan creation.

Every change to the answer is audit-logged with the old value and the new one, because
"who decided this scan could be deleted, and when" is exactly the question a deletion
has to be able to answer later.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import utcnow
from app.models.tables import AppSetting, Scan, User
from app.services import audit

log = logging.getLogger(__name__)

# The soft-delete reason column is String(64); trim rather than reject an over-long one.
DELETED_REASON_MAX = 64

# The administrator-tunable auto-deletion window, and the bounds it is clamped to.
RETENTION_DAYS_KEY = "retention_days"
RETENTION_DAYS_MIN = 1
RETENTION_DAYS_MAX = 3650


def _aware(dt: datetime | None) -> datetime | None:
    """A timestamp read back from the database is tz-aware on PostgreSQL and tz-naive
    on SQLite. Every timestamp this system writes is UTC (`datetime.now(UTC)`), so a
    naive one is a UTC one that lost its tag on the round trip. Re-tag it before it is
    compared against `utcnow()`, which is always aware."""
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


def _clamp_days(days: int) -> int:
    return max(RETENTION_DAYS_MIN, min(RETENTION_DAYS_MAX, days))


def get_retention_days(db: Session) -> int:
    """The auto-deletion window in force: an administrator's stored override, or the
    config default when none has been set."""
    row = db.get(AppSetting, RETENTION_DAYS_KEY)
    if row is not None:
        try:
            return _clamp_days(int(row.value))
        except (TypeError, ValueError):
            log.warning(
                "Stored %s is %r, not an integer; using the configured default.",
                RETENTION_DAYS_KEY, row.value,
            )
    return settings.retention_days


def set_retention_days(db: Session, days: int, actor: User) -> int:
    """Change the auto-deletion window. Clamped to a sane range, audit-logged, and in
    force for the next run of the job and every eligibility read after this. The caller
    commits."""
    clamped = _clamp_days(days)
    row = db.get(AppSetting, RETENTION_DAYS_KEY)
    before = int(row.value) if row is not None and row.value.isdigit() else settings.retention_days
    if row is None:
        row = AppSetting(key=RETENTION_DAYS_KEY, value=str(clamped))
        db.add(row)
    else:
        row.value = str(clamped)
    row.updated_at = utcnow()
    row.updated_by_id = actor.id

    audit.record(
        db,
        action=audit.Action.RETENTION_WINDOW_CHANGED,
        entity_type="app_setting",
        entity_id=RETENTION_DAYS_KEY,
        actor=actor,
        before={"days": before},
        after={"days": clamped},
    )
    return clamped


def effective_retention_days(db: Session) -> int:
    """The window, in days, that governs auto-deletion eligibility. Kept as its own
    name because every eligibility path already calls it; the administrator override
    lives one level down in `get_retention_days`."""
    return get_retention_days(db)


@dataclass(frozen=True)
class RetentionState:
    """How a scan stands with respect to deletion, for the API and the UI."""

    case_open: bool | None
    decided_at: datetime | None
    decided_by_id: str | None
    eligible_for_deletion: bool
    # When it becomes eligible (case_open is False), or None otherwise.
    eligible_on: datetime | None
    # A sentence an officer can read: "Retained — a case is open." etc.
    summary: str


def describe(scan: Scan, retention_days: int) -> RetentionState:
    """The retention state of one scan. Pure — no queries, no clock beyond `utcnow`."""
    if scan.case_open is None:
        return RetentionState(
            case_open=None,
            decided_at=None,
            decided_by_id=None,
            eligible_for_deletion=False,
            eligible_on=None,
            summary=(
                "Not yet reviewed for retention. It will not be auto-deleted until an "
                "officer records whether a case is open."
            ),
        )
    if scan.case_open:
        return RetentionState(
            case_open=True,
            decided_at=_aware(scan.case_open_decided_at),
            decided_by_id=scan.case_open_decided_by_id,
            eligible_for_deletion=False,
            eligible_on=None,
            summary="Retained. A case is open on this scan; it is never auto-deleted.",
        )

    decided = _aware(scan.case_open_decided_at) or utcnow()
    eligible_on = decided + timedelta(days=retention_days)
    eligible = utcnow() >= eligible_on
    if eligible:
        summary = (
            f"Eligible for auto-deletion. No case is open, and more than "
            f"{retention_days} days have passed since that decision."
        )
    else:
        summary = (
            f"No case is open. Eligible for auto-deletion on "
            f"{eligible_on.date().isoformat()} — {retention_days} days after the "
            "decision was recorded."
        )
    return RetentionState(
        case_open=False,
        decided_at=_aware(scan.case_open_decided_at),
        decided_by_id=scan.case_open_decided_by_id,
        eligible_for_deletion=eligible,
        eligible_on=eligible_on,
        summary=summary,
    )


def record_decision(db: Session, scan: Scan, case_open: bool, actor: User) -> None:
    """Set or change the officer's answer, and audit the change.

    The decision timestamp is refreshed on every change — including when the answer is
    reaffirmed to the same value — so the deletion clock always runs from the most
    recent time an officer actively looked at this and said "no case is open". A scan
    reopened and then closed again a month later gets a fresh 30 days from the second
    close, which is the safe reading.
    """
    before = {
        "case_open": scan.case_open,
        "decided_at": scan.case_open_decided_at.isoformat() if scan.case_open_decided_at else None,
    }
    scan.case_open = case_open
    scan.case_open_decided_at = utcnow()
    scan.case_open_decided_by_id = actor.id

    audit.record(
        db,
        action=audit.Action.RETENTION_DECISION,
        entity_type="scan",
        entity_id=scan.id,
        actor=actor,
        before=before,
        after={
            "case_open": case_open,
            "decided_at": scan.case_open_decided_at.isoformat(),
        },
    )


def eligible_scan_ids(db: Session, *, now: datetime | None = None) -> list[str]:
    """Every scan the auto-delete job may remove: case_open is False, window elapsed,
    not already deleted. case_open True and case_open None are both excluded by the
    `is_(False)` filter — neither is a decision to allow deletion."""
    now = now or utcnow()
    cutoff = now - timedelta(days=effective_retention_days(db))
    rows = db.execute(
        select(Scan.id).where(
            Scan.case_open.is_(False),
            Scan.case_open_decided_at.is_not(None),
            Scan.case_open_decided_at <= cutoff,
            Scan.deleted_at.is_(None),
        )
    ).scalars()
    return list(rows)


def soft_delete(
    db: Session,
    scan: Scan,
    *,
    actor: User | None,
    reason: str | None,
    automated: bool = False,
) -> None:
    """Mark a scan deleted without removing its row.

    The scan's existence and this deletion event stay in the database and the audit
    trail permanently — a soft delete, never a hard one. A manual delete names the
    officer or administrator who made it; the scheduled job passes `actor=None` and
    `automated=True`.

    Manual deletion is an explicit act by an authorised person and does not consult
    `case_open`: a scan with a case open is still manually deletable. Only
    `run_auto_deletion` respects the retention answer. The caller commits.
    """
    now = utcnow()
    scan.deleted_at = now
    scan.deleted_by_id = actor.id if actor else None
    scan.deleted_reason = (reason or "").strip()[:DELETED_REASON_MAX] or None

    decided = _aware(scan.case_open_decided_at)
    audit.record(
        db,
        action=audit.Action.SCAN_DELETED,
        entity_type="scan",
        entity_id=scan.id,
        actor=actor,
        before={"deleted_at": None},
        after={
            "deleted_at": now.isoformat(),
            "reason": scan.deleted_reason,
            "automated": automated,
            # The retention state at the moment of deletion, so "why was this removed,
            # and was it allowed" is answerable from the log alone.
            "case_open": scan.case_open,
            "case_open_decided_at": decided.isoformat() if decided else None,
        },
    )


def run_auto_deletion(db: Session, *, now: datetime | None = None) -> list[str]:
    """Soft-delete every scan the retention policy has made eligible, logging each.

    Eligible means exactly one thing: an officer recorded case_open = False and the
    configured window has since elapsed. case_open = True and case_open = None are
    never touched, at any age. Commits once at the end; returns the ids removed.
    """
    deleted: list[str] = []
    for scan_id in eligible_scan_ids(db, now=now):
        scan = db.get(Scan, scan_id)
        if scan is None or scan.deleted_at is not None:
            continue
        soft_delete(
            db, scan, actor=None, reason="retention window elapsed", automated=True
        )
        deleted.append(scan_id)

    if deleted:
        db.commit()
        log.info(
            "Auto-deletion soft-deleted %d scan(s) past the %d-day retention window: %s",
            len(deleted), effective_retention_days(db), ", ".join(deleted),
        )
    return deleted
