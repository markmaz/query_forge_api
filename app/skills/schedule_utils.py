"""
app/skills/schedule_utils.py

Utilities for cron validation, next-run preview, and scheduler health.
Used by the API, the skill runner, and the SkillBuilder UI endpoint.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import pytz
import valkey
from croniter import croniter

from app.config import VALKEY_ADDRESS, VALKEY_PORT

logger = logging.getLogger(__name__)

# Minimum allowed interval between scheduled runs (5 minutes = 300 seconds)
MIN_INTERVAL_SECONDS = 300


def _valkey_client() -> valkey.Valkey:
    return valkey.Valkey(
        host=str(VALKEY_ADDRESS or "localhost"),
        port=int(VALKEY_PORT or 6379),
        db=0,
        decode_responses=True,
        socket_timeout=1.5,
    )


# ---------------------------------------------------------------------------
# Cron validation
# ---------------------------------------------------------------------------


def validate_cron(expression: str, timezone_name: str = "UTC") -> list[str]:
    """
    Validate a cron expression and enforce minimum frequency.
    Returns a list of error strings (empty = valid).
    """
    errors: list[str] = []

    if not expression or not expression.strip():
        errors.append("Cron expression cannot be empty.")
        return errors

    if not croniter.is_valid(expression):
        errors.append(f"Invalid cron expression: {expression!r}")
        return errors

    try:
        pytz.timezone(timezone_name)
    except pytz.UnknownTimeZoneError:
        errors.append(f"Unknown timezone: {timezone_name!r}")
        return errors

    # Check minimum interval — get two consecutive runs and measure gap
    try:
        now = datetime.now(timezone.utc)
        cron = croniter(expression, now)
        first = cron.get_next(float)
        second = cron.get_next(float)
        interval = second - first
        if interval < MIN_INTERVAL_SECONDS:
            errors.append(
                f"Schedule would run every {int(interval)}s — "
                f"minimum allowed interval is {MIN_INTERVAL_SECONDS}s (5 minutes)."
            )
    except Exception as exc:
        errors.append(f"Could not evaluate cron interval: {exc}")

    return errors


# ---------------------------------------------------------------------------
# Next-run preview (powers the UI "next 5 runs" display)
# ---------------------------------------------------------------------------


def next_n_runs(
    expression: str,
    timezone_name: str = "UTC",
    n: int = 5,
    from_dt: datetime | None = None,
) -> list[str]:
    """
    Return the next N run times for a cron expression as ISO strings.
    Returns an empty list if the expression is invalid.
    """
    if not croniter.is_valid(expression):
        return []

    try:
        tz = pytz.timezone(timezone_name)
        base = (from_dt or datetime.now(timezone.utc)).astimezone(tz)
        cron = croniter(expression, base)
        return [
            cron.get_next(datetime).isoformat()
            for _ in range(n)
        ]
    except Exception as exc:
        logger.warning("next_n_runs failed for %r: %s", expression, exc)
        return []


# ---------------------------------------------------------------------------
# Scheduler health (powers GET /api/v1/skills/scheduler/status)
# ---------------------------------------------------------------------------


def get_scheduler_health() -> dict[str, Any]:
    """
    Check whether the Celery Beat scheduler is alive and return stats.

    Reads the last dispatch time from Valkey (set by dispatch_due_skills).
    If the key is missing or stale, the scheduler is considered unhealthy.
    """
    BEAT_HEARTBEAT_KEY = "skills:scheduler:last_dispatch"
    STALE_THRESHOLD_SECONDS = 180  # Beat fires every 60s — 3 misses = unhealthy

    try:
        client = _valkey_client()
        raw = client.get(BEAT_HEARTBEAT_KEY)
        if raw is None:
            return {
                "healthy": False,
                "reason": "No heartbeat recorded — Beat may not be running.",
                "last_dispatch_at": None,
                "seconds_since_dispatch": None,
            }

        last_dispatch_at = datetime.fromisoformat(raw)
        seconds_ago = (datetime.now(timezone.utc) - last_dispatch_at).total_seconds()

        return {
            "healthy": seconds_ago < STALE_THRESHOLD_SECONDS,
            "reason": None if seconds_ago < STALE_THRESHOLD_SECONDS else f"Last dispatch was {int(seconds_ago)}s ago.",
            "last_dispatch_at": last_dispatch_at.isoformat(),
            "seconds_since_dispatch": int(seconds_ago),
        }
    except Exception as exc:
        logger.error("Scheduler health check failed: %s", exc)
        return {
            "healthy": False,
            "reason": f"Health check error: {exc}",
            "last_dispatch_at": None,
            "seconds_since_dispatch": None,
        }


def record_dispatch_heartbeat() -> None:
    """
    Write the current UTC time to Valkey as the Beat heartbeat.
    Called at the top of dispatch_due_skills on every tick.
    TTL is 10 minutes — if Beat dies the key expires naturally.
    """
    BEAT_HEARTBEAT_KEY = "skills:scheduler:last_dispatch"
    try:
        client = _valkey_client()
        client.setex(
            BEAT_HEARTBEAT_KEY,
            600,  # 10 minute TTL
            datetime.now(timezone.utc).isoformat(),
        )
    except Exception as exc:
        logger.warning("Failed to record dispatch heartbeat: %s", exc)
