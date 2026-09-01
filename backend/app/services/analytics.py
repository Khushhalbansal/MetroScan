"""Aggregations for the enforcement dashboard.

Everything here is a count over stored findings. Nothing is re-judged and nothing is
inferred: a dashboard that recomputed verdicts would be a second implementation of the
rule engine, and the two would disagree the first time a rule changed.

Two counting decisions carry the invariants upward from a single scan to the whole
estate, and both are the reason this module exists rather than a few inline queries:

  * Scans that decided nothing are counted and reported separately, never folded into
    a compliance rate. A district whose photographs were unusable has not been shown to
    be compliant, and averaging its inconclusive scans towards either end is a claim
    about products nobody assessed.
  * Failure counts are taken from the finding's *current* status, so an officer who
    overrules a violation removes it from the enforcement totals — while the automated
    verdict stays on the scan for anyone who reopens it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, timedelta
from typing import TypedDict

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.enums import FindingStatus, Severity, Verdict
from app.models.tables import Finding, Product, Scan

log = logging.getLogger(__name__)


# Typed rather than plain dicts: every `compliance_rate` in this module is float | None
# and the None is load-bearing, so the shapes say which keys may be absent a value and
# which may not. A bare dict[str, int | None] loses that per-key and turns the schema
# construction at the route into an unchecked splat.
class Totals(TypedDict):
    scans: int
    compliant: int
    non_compliant: int
    inconclusive: int
    concluded: int
    compliance_rate: float | None
    open_reviews: int
    officer_decisions: int


class CalibrationShare(TypedDict):
    scans: int
    calibrated: int
    uncalibrated: int
    calibrated_rate: float | None


@dataclass(frozen=True)
class Window:
    """The period a dashboard covers. Always stated, never implied."""

    since: date
    until: date

    @classmethod
    def last(cls, days: int) -> Window:
        today = date.today()
        return cls(since=today - timedelta(days=days), until=today)


def _in_window(statement, window: Window):
    return statement.where(Scan.scan_date >= window.since, Scan.scan_date <= window.until)


def totals(db: Session, window: Window) -> Totals:
    """Headline counts.

    `compliance_rate` is deliberately None when no scan in the window reached a
    conclusion. A percentage over zero decided scans is not a low number, it is not a
    number, and printing 0% would read as an accusation against a district that simply
    could not photograph anything.
    """
    rows = db.execute(_in_window(select(Scan.verdict, func.count()), window).group_by(Scan.verdict))
    by_verdict = dict(rows.all())

    compliant = by_verdict.get(Verdict.COMPLIANT, 0)
    non_compliant = by_verdict.get(Verdict.NON_COMPLIANT, 0)
    inconclusive = by_verdict.get(Verdict.INCONCLUSIVE, 0)
    concluded = compliant + non_compliant

    open_reviews = db.execute(
        _in_window(
            select(func.count())
            .select_from(Finding)
            .join(Scan, Scan.id == Finding.scan_id)
            .where(Finding.status == FindingStatus.NEEDS_REVIEW),
            window,
        )
    ).scalar_one()

    overrides = db.execute(
        _in_window(
            select(func.count())
            .select_from(Finding)
            .join(Scan, Scan.id == Finding.scan_id)
            .where(Finding.original_status.is_not(None)),
            window,
        )
    ).scalar_one()

    return {
        "scans": compliant + non_compliant + inconclusive,
        "compliant": compliant,
        "non_compliant": non_compliant,
        "inconclusive": inconclusive,
        "concluded": concluded,
        "compliance_rate": (
            round(100.0 * compliant / concluded, 1) if concluded else None
        ),
        "open_reviews": int(open_reviews),
        "officer_decisions": int(overrides),
    }


def top_violations(db: Session, window: Window, limit: int = 10) -> list[dict]:
    """Which rules are actually being broken, most frequent first.

    Counted on the finding's current status, so a violation an officer has overruled
    stops counting as one here. The scan still records what the software found.
    """
    statement = _in_window(
        select(
            Finding.rule_id,
            Finding.title,
            Finding.citation,
            Finding.severity,
            func.count().label("n"),
        )
        .join(Scan, Scan.id == Finding.scan_id)
        .where(Finding.status == FindingStatus.FAIL),
        window,
    ).group_by(Finding.rule_id, Finding.title, Finding.citation, Finding.severity)

    rows = db.execute(statement.order_by(func.count().desc()).limit(limit)).all()
    return [
        {
            "rule_id": rule_id,
            "title": title,
            "citation": citation,
            "severity": Severity(severity).value,
            "count": int(count),
        }
        for rule_id, title, citation, severity, count in rows
    ]


def by_category(db: Session, window: Window) -> list[dict]:
    """Compliance by product category, with the inconclusive scans kept visible."""
    statement = _in_window(
        select(Product.category, Scan.verdict, func.count())
        .select_from(Scan)
        .join(Product, Product.id == Scan.product_id),
        window,
    ).group_by(Product.category, Scan.verdict)

    buckets: dict[str, dict[str, int]] = {}
    for category, verdict, count in db.execute(statement).all():
        name = category or "Uncategorised"
        bucket = buckets.setdefault(
            name, {"compliant": 0, "non_compliant": 0, "inconclusive": 0}
        )
        if verdict == Verdict.COMPLIANT:
            bucket["compliant"] += count
        elif verdict == Verdict.NON_COMPLIANT:
            bucket["non_compliant"] += count
        else:
            bucket["inconclusive"] += count

    out = []
    for name, bucket in buckets.items():
        concluded = bucket["compliant"] + bucket["non_compliant"]
        out.append(
            {
                "category": name,
                **bucket,
                "scans": concluded + bucket["inconclusive"],
                "compliance_rate": (
                    round(100.0 * bucket["compliant"] / concluded, 1) if concluded else None
                ),
            }
        )
    return sorted(out, key=lambda row: row["scans"], reverse=True)


def unmeasured_share(db: Session, window: Window) -> CalibrationShare:
    """How often a scan arrived with no scale reference in frame.

    This is the single most actionable number for an enforcement office. Every scan
    without a fiducial leaves every Rule 8 question unanswered, and the fix is not
    software — it is telling inspectors to put the card in the photograph. A dashboard
    that hides this reports a system working better than it is.
    """
    total = db.execute(_in_window(select(func.count()).select_from(Scan), window)).scalar_one()
    calibrated = db.execute(
        _in_window(
            select(func.count()).select_from(Scan).where(Scan.mm_per_px.is_not(None)), window
        )
    ).scalar_one()
    return {
        "scans": int(total),
        "calibrated": int(calibrated),
        "uncalibrated": int(total) - int(calibrated),
        "calibrated_rate": round(100.0 * calibrated / total, 1) if total else None,
    }


# Above this many days in the window, the per-day trend is bucketed by ISO week so
# the bars stay legible (a 365-day window is 52 bars, not 365 hairlines).
DAILY_TREND_MAX_DAYS = 92


def daily(db: Session, window: Window) -> list[dict]:
    """Scans per verdict over time, oldest first, for the trend chart.

    Every bucket in the window is returned, including the empty ones — a day (or
    week) with no scans is a real reading, and a chart that omits it turns sparse
    activity into a false run of solid bars. Buckets are days for a window up to
    ~13 weeks, ISO weeks beyond that.
    """
    span_days = (window.until - window.since).days + 1
    weekly = span_days > DAILY_TREND_MAX_DAYS

    statement = _in_window(
        select(Scan.scan_date, Scan.verdict, func.count()), window
    ).group_by(Scan.scan_date, Scan.verdict)

    def key_of(d: date) -> date:
        # Monday of that ISO week, so weekly buckets are stable and label cleanly.
        return d - timedelta(days=d.weekday()) if weekly else d

    buckets: dict[date, dict[str, int]] = {}
    step = timedelta(weeks=1) if weekly else timedelta(days=1)
    cursor = key_of(window.since)
    while cursor <= window.until:
        buckets[cursor] = {"compliant": 0, "non_compliant": 0, "inconclusive": 0}
        cursor += step

    for scan_date, verdict, count in db.execute(statement).all():
        bucket = buckets.setdefault(
            key_of(scan_date), {"compliant": 0, "non_compliant": 0, "inconclusive": 0}
        )
        if verdict == Verdict.COMPLIANT:
            bucket["compliant"] += count
        elif verdict == Verdict.NON_COMPLIANT:
            bucket["non_compliant"] += count
        else:
            bucket["inconclusive"] += count

    return [
        {"date": day.isoformat(), **counts, "scans": sum(counts.values())}
        for day, counts in sorted(buckets.items())
    ]
