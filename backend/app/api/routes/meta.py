"""Health, and which rulesets this server can judge against."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from app.core.config import settings
from app.core.db import engine
from app.core.schema_state import inspect_schema
from app.pipeline.engine_ocr import get_engine
from app.rules.loader import _all_rulesets, available_versions, ruleset_by_version
from app.schemas.scan import HealthOut, RulesetOut

router = APIRouter(tags=["meta"])


def _out(rs) -> RulesetOut:
    return RulesetOut(
        version=rs.version,
        effective_date=rs.effective_date,
        description=rs.description,
        source=rs.source,
        rule_count=len(rs.rules),
    )


@router.get("/health", response_model=HealthOut, summary="Liveness and what is loaded")
def health() -> HealthOut:
    """Reports the OCR engine by name.

    Worth watching: the engine falls back to a stub when the OCR weights cannot be
    loaded, and a stub reads no text at all. The pipeline handles that correctly —
    nothing is declared missing on a scan that read nothing — but a server quietly
    running on the stub would return INCONCLUSIVE for every package, so the engine in
    use is stated here rather than assumed.
    """
    report = inspect_schema(engine)
    return HealthOut(
        status="ok" if report.writable else "degraded",
        environment=settings.environment,
        ocr_engine=get_engine().name,
        rulesets=available_versions(),
        database=str(report.state),
        database_detail=report.message,
    )


@router.get("/rulesets", response_model=list[RulesetOut], summary="Every ruleset on disk")
def list_rulesets() -> list[RulesetOut]:
    return [_out(rs) for rs in _all_rulesets()]


@router.get("/rulesets/{version}", response_model=RulesetOut, summary="One ruleset")
def get_ruleset(version: str) -> RulesetOut:
    try:
        return _out(ruleset_by_version(version))
    except KeyError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No ruleset {version!r}.") from exc
