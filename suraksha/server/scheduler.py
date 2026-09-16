"""Background scheduler: hourly ingestion of data + risk re-scoring."""

from __future__ import annotations

import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from suraksha.config import get_settings
from suraksha.data.pipeline import run_pipeline
from suraksha.delivery.alerts import sweep_subscribers

logger = logging.getLogger(__name__)
_scheduler: AsyncIOScheduler | None = None


async def _job() -> None:
    try:
        summary = await run_pipeline()
        logger.info(
            "scheduled ingest: %d districts, %d risk rows, %d errors",
            summary["districts"],
            summary["risk_rows"],
            len(summary["errors"]),
        )
    except Exception:  # noqa: BLE001
        logger.exception("scheduled ingest failed")


async def _alert_job() -> None:
    """Daily proactive-alert sweep over subscribers (after the morning ingest)."""
    try:
        summary = await sweep_subscribers()
        logger.info("scheduled alert sweep: %s", summary)
    except Exception:  # noqa: BLE001
        logger.exception("scheduled alert sweep failed")


def start_scheduler() -> AsyncIOScheduler | None:
    """Start hourly ingestion; call once from the CLI/server startup."""
    global _scheduler
    minutes = get_settings().ingest_interval_minutes
    if minutes <= 0:
        logger.info("scheduler disabled (INGEST_INTERVAL_MINUTES<=0)")
        return None
    _scheduler = AsyncIOScheduler()
    _scheduler.add_job(_job, IntervalTrigger(minutes=minutes), id="ingest", max_instances=1)
    _scheduler.add_job(
        _alert_job,
        CronTrigger(hour=7, minute=30),
        id="alert-sweep",
        max_instances=1,
        misfire_grace_time=3600,
    )
    _scheduler.start()
    logger.info("scheduler started: ingest every %d minutes", minutes)
    return _scheduler


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None
