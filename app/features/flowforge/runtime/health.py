from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import valkey
from valkey.exceptions import ValkeyError

from app.config import VALKEY_ADDRESS, VALKEY_PORT

logger = logging.getLogger(__name__)

FLOWFORGE_WORKER_HEARTBEAT_KEY = "flowforge:worker:last_dispatch"
FLOWFORGE_WORKER_HEARTBEAT_TTL_SECONDS = 600
FLOWFORGE_WORKER_STALE_SECONDS = 180
FLOWFORGE_HEALTH_FALLBACK_ERRORS = (OSError, ValkeyError, TypeError, ValueError)


def _valkey_client() -> valkey.Valkey:
    return valkey.Valkey(
        host=str(VALKEY_ADDRESS or "localhost"),
        port=int(VALKEY_PORT or 6379),
        db=0,
        decode_responses=True,
        socket_timeout=1.5,
    )


def record_flowforge_worker_heartbeat(*, task_name: str) -> None:
    payload = {
        "task_name": str(task_name or "unknown"),
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        _valkey_client().setex(
            FLOWFORGE_WORKER_HEARTBEAT_KEY,
            FLOWFORGE_WORKER_HEARTBEAT_TTL_SECONDS,
            f"{payload['recorded_at']}|{payload['task_name']}",
        )
    except FLOWFORGE_HEALTH_FALLBACK_ERRORS as exc:
        logger.warning("Failed to record FlowForge worker heartbeat: %s", exc)


def get_flowforge_worker_health() -> dict[str, Any]:
    try:
        raw = _valkey_client().get(FLOWFORGE_WORKER_HEARTBEAT_KEY)
        if raw is None:
            return {
                "healthy": False,
                "reason": "No FlowForge worker heartbeat recorded.",
                "last_dispatch_at": None,
                "seconds_since_dispatch": None,
                "task_name": None,
            }

        raw_text = str(raw)
        timestamp_text, _, task_name = raw_text.partition("|")
        last_dispatch_at = datetime.fromisoformat(timestamp_text)
        if last_dispatch_at.tzinfo is None:
            last_dispatch_at = last_dispatch_at.replace(tzinfo=timezone.utc)
        seconds_ago = int((datetime.now(timezone.utc) - last_dispatch_at).total_seconds())
        healthy = seconds_ago < FLOWFORGE_WORKER_STALE_SECONDS
        return {
            "healthy": healthy,
            "reason": None if healthy else f"Last FlowForge worker heartbeat was {seconds_ago}s ago.",
            "last_dispatch_at": last_dispatch_at.isoformat(),
            "seconds_since_dispatch": seconds_ago,
            "task_name": task_name or None,
        }
    except FLOWFORGE_HEALTH_FALLBACK_ERRORS as exc:
        logger.error("FlowForge worker health check failed: %s", exc)
        return {
            "healthy": False,
            "reason": f"Health check error: {exc}",
            "last_dispatch_at": None,
            "seconds_since_dispatch": None,
            "task_name": None,
        }
