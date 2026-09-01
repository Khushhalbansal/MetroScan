"""Dashboard wire shapes.

`compliance_rate` is `float | None` throughout, and the None is load-bearing: it means
no scan in this slice reached a conclusion. A dashboard that rendered that as 0% would
accuse a district whose photographs were simply unusable, which is the same mistake at
estate scale that the rule engine refuses to make on a single pack.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field


class WindowOut(BaseModel):
    since: date
    until: date
    days: int


class TotalsOut(BaseModel):
    scans: int
    compliant: int
    non_compliant: int
    inconclusive: int
    concluded: int = Field(description="Scans that reached compliant or non-compliant.")
    compliance_rate: float | None = Field(
        default=None,
        description="Percent of concluded scans that complied. Null when none concluded.",
    )
    open_reviews: int = Field(description="Findings still waiting on an officer.")
    officer_decisions: int


class ViolationOut(BaseModel):
    rule_id: str
    title: str
    citation: str
    severity: str
    count: int


class CategoryOut(BaseModel):
    category: str
    scans: int
    compliant: int
    non_compliant: int
    inconclusive: int
    compliance_rate: float | None = None


class CalibrationSummaryOut(BaseModel):
    """How many scans arrived with a scale reference in frame."""

    scans: int
    calibrated: int
    uncalibrated: int
    calibrated_rate: float | None = None


class DayOut(BaseModel):
    date: date
    scans: int
    compliant: int
    non_compliant: int
    inconclusive: int


class DashboardOut(BaseModel):
    window: WindowOut
    totals: TotalsOut
    top_violations: list[ViolationOut]
    by_category: list[CategoryOut]
    calibration: CalibrationSummaryOut
    daily: list[DayOut]
