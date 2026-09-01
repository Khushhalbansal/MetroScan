"""Administrator controls that are not about one scan or one user.

Today that is the retention policy: the length of the auto-deletion window, and a
manual trigger for the job that enforces it. Both are admin-only and audit-logged.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, status
from starlette.concurrency import run_in_threadpool

from app.api.deps import AdminOnly, WritableDb
from app.schemas.scan import RetentionWindowOut, RetentionWindowRequest
from app.services import retention

log = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get(
    "/retention-window",
    response_model=RetentionWindowOut,
    summary="The auto-deletion window currently in force",
)
def get_retention_window(db: WritableDb, admin: AdminOnly) -> RetentionWindowOut:
    return RetentionWindowOut(days=retention.get_retention_days(db))


@router.put(
    "/retention-window",
    response_model=RetentionWindowOut,
    summary="Set the auto-deletion window",
)
def set_retention_window(
    body: RetentionWindowRequest, db: WritableDb, admin: AdminOnly
) -> RetentionWindowOut:
    """Change how long after an officer records `case_open = False` a scan waits before
    the scheduled job may remove it. Clamped to 1–3650 days and audit-logged with the
    previous value. Takes effect for the next run of the job and every eligibility read
    after this."""
    days = retention.set_retention_days(db, body.days, admin)
    db.commit()
    return RetentionWindowOut(days=days)


@router.post(
    "/retention/run",
    status_code=status.HTTP_200_OK,
    summary="Run the auto-deletion job now",
)
async def run_retention_now(db: WritableDb, admin: AdminOnly) -> dict[str, object]:
    """Soft-delete every scan the retention policy has made eligible, immediately.

    The same operation a system cron runs via `python -m app.cli prune-scans`; this is
    the button for an operator without shell access. Only scans an officer marked
    `case_open = False` whose window has elapsed are touched — never a case that is
    open, never one nobody has reviewed.
    """
    deleted = await run_in_threadpool(retention.run_auto_deletion, db)
    return {"deleted": deleted, "count": len(deleted)}
