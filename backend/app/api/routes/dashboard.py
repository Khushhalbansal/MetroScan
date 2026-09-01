"""The enforcement dashboard's numbers."""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import AnyOfficer, DbSession
from app.schemas.dashboard import (
    CalibrationSummaryOut,
    CategoryOut,
    DashboardOut,
    DayOut,
    TotalsOut,
    ViolationOut,
    WindowOut,
)
from app.services import analytics

log = logging.getLogger(__name__)

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("", response_model=DashboardOut, summary="Enforcement overview")
def dashboard(
    db: DbSession,
    officer: AnyOfficer,
    days: Annotated[int, Query(ge=1, le=730, description="Window length in days.")] = 90,
) -> DashboardOut:
    """Counts over the scans filed in the window.

    Nothing here is recomputed from images or re-judged: every number is a count over
    findings as they currently stand, so the dashboard and the scan an officer opens
    from it can never disagree.
    """
    window = analytics.Window.last(days)
    return DashboardOut(
        window=WindowOut(since=window.since, until=window.until, days=days),
        totals=TotalsOut(**analytics.totals(db, window)),
        top_violations=[ViolationOut(**row) for row in analytics.top_violations(db, window)],
        by_category=[CategoryOut(**row) for row in analytics.by_category(db, window)],
        calibration=CalibrationSummaryOut(**analytics.unmeasured_share(db, window)),
        daily=[DayOut(**row) for row in analytics.daily(db, window)],
    )
