"""The in-process side of Feature 6: run the retention auto-deletion job on a timer
while the API is up.

`retention.run_auto_deletion` is the whole of the logic and is exhaustively tested on
its own. This module is only the clock: wait the interval, run one sweep on a worker
thread (the job is synchronous DB work), log the outcome, and never let a single
failed sweep stop the loop. It is stopped cleanly on shutdown.

Deployments that would rather drive it from a system cron or a Kubernetes CronJob can
set `retention_sweep_enabled = False` and schedule `python -m app.cli prune-scans`.
"""

from __future__ import annotations

import asyncio
import logging

from app.core.config import settings
from app.core.db import SessionLocal
from app.services import retention

log = logging.getLogger(__name__)


def _sweep_once() -> list[str]:
    """One synchronous sweep on its own session. Returns the ids soft-deleted."""
    db = SessionLocal()
    try:
        return retention.run_auto_deletion(db)
    finally:
        db.close()


async def sweep_once() -> list[str]:
    """Run one sweep off the event loop, swallowing and logging any failure so the
    caller's loop survives it."""
    try:
        deleted = await asyncio.to_thread(_sweep_once)
        if deleted:
            log.info("Retention sweep soft-deleted %d scan(s).", len(deleted))
        return deleted
    except Exception:  # one bad sweep must not end the loop  # noqa: BLE001
        log.exception("Retention sweep failed; will retry on the next interval.")
        return []


async def run_periodically(
    *,
    interval_seconds: float,
    initial_delay_seconds: float,
    stop: asyncio.Event,
) -> None:
    """Sweep once after the initial delay, then every `interval_seconds`, until
    `stop` is set. Waiting on `stop` rather than sleeping means shutdown is immediate,
    not "up to an interval away"."""
    if await _slept(stop, initial_delay_seconds):
        return
    await sweep_once()
    while not stop.is_set():
        if await _slept(stop, interval_seconds):
            return
        await sweep_once()


async def _slept(stop: asyncio.Event, seconds: float) -> bool:
    """Wait up to `seconds`. Returns True if `stop` was set during the wait (caller
    should exit), False if the full time elapsed."""
    try:
        await asyncio.wait_for(stop.wait(), timeout=seconds)
        return True
    except TimeoutError:
        return False


def attach(app) -> None:
    """Wire start/stop of the periodic sweep to a FastAPI app's lifecycle."""
    state: dict[str, object] = {}

    @app.on_event("startup")
    async def _start() -> None:
        if not settings.retention_sweep_enabled:
            log.info(
                "In-process retention sweep is disabled; run `python -m app.cli "
                "prune-scans` from a scheduler instead."
            )
            return
        stop = asyncio.Event()
        state["stop"] = stop
        state["task"] = asyncio.create_task(
            run_periodically(
                interval_seconds=settings.retention_sweep_interval_hours * 3600,
                initial_delay_seconds=settings.retention_sweep_initial_delay_seconds,
                stop=stop,
            )
        )
        log.info(
            "In-process retention sweep started (every %.1f h).",
            settings.retention_sweep_interval_hours,
        )

    @app.on_event("shutdown")
    async def _stop() -> None:
        stop = state.get("stop")
        task = state.get("task")
        if isinstance(stop, asyncio.Event):
            stop.set()
        if isinstance(task, asyncio.Task):
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=5.0)
            except (TimeoutError, asyncio.CancelledError):
                task.cancel()
