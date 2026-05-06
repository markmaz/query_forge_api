from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional
from urllib.parse import urlsplit, urlunsplit

import requests
import valkey
from requests import RequestException
from sqlalchemy.exc import SQLAlchemyError

from app.celery_app import celery
from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.config import QDRANT_URL, VALKEY_ADDRESS, VALKEY_CONFIG, VALKEY_PORT, VLLM_BASE_URL, VLLM_MODEL
from app.config.mcp_oauth_config import load_mcp_oauth_config
from app.features.flowforge.runtime.health import get_flowforge_worker_health
from app.ports.sql_executor import ForgeQueryPort

logger = logging.getLogger(__name__)


class AdminHealthService:
    def __init__(
        self,
        *,
        sql: Optional[ForgeQueryPort] = None,
        vllm_base_url: Optional[str] = None,
        vllm_model: Optional[str] = None,
        qdrant_url: Optional[str] = None,
        mcp_resource_url: Optional[str] = None,
    ) -> None:
        self._sql = sql or ForgeMetaSQL()
        self._vllm_base_url = vllm_base_url or VLLM_BASE_URL
        self._vllm_model = vllm_model or VLLM_MODEL
        self._qdrant_url = qdrant_url or QDRANT_URL
        self._mcp_resource_url = (mcp_resource_url or load_mcp_oauth_config().mcp_resource_url).rstrip("/")

    def check_all(self) -> Dict[str, Any]:
        checks: Dict[str, Any] = {}
        checks["app"] = self._check_app()
        checks["mysql"] = self._check_mysql()
        checks["vllm"] = self._check_vllm()
        checks["qdrant"] = self._check_qdrant()
        checks["mcp"] = self._check_mcp()
        checks["broker"] = self.check_broker()
        checks["flowforge"] = self._check_flowforge()

        statuses = [c["status"] for c in checks.values()]
        if all(s == "ok" for s in statuses):
            overall = "healthy"
        elif any(s == "ok" for s in statuses):
            overall = "degraded"
        else:
            overall = "unhealthy"

        return {"overall": overall, "checks": checks}

    def _check_app(self) -> Dict[str, Any]:
        return {"status": "ok"}

    def _check_mysql(self) -> Dict[str, Any]:
        start = time.perf_counter()
        try:
            rows = self._sql.execute_query("SELECT 1")
            latency_ms = int((time.perf_counter() - start) * 1000)
            if rows and rows[0][0] == 1:
                return {"status": "ok", "latency_ms": latency_ms}
            return {"status": "error", "latency_ms": latency_ms, "error": "unexpected result"}
        except (SQLAlchemyError, OSError, RuntimeError, ValueError) as exc:
            latency_ms = int((time.perf_counter() - start) * 1000)
            logger.exception("MySQL health check failed")
            return {"status": "error", "latency_ms": latency_ms, "error": str(exc)}

    def _check_vllm(self) -> Dict[str, Any]:
        url = f"{self._vllm_base_url}/v1/models"
        start = time.perf_counter()
        try:
            resp = requests.get(url, timeout=10)
            latency_ms = int((time.perf_counter() - start) * 1000)
            resp.raise_for_status()
            return {
                "status": "ok",
                "latency_ms": latency_ms,
                "model": self._vllm_model,
                "upstream": resp.json(),
            }
        except (RequestException, OSError, ValueError) as exc:
            latency_ms = int((time.perf_counter() - start) * 1000)
            logger.exception("vLLM health check failed")
            return {"status": "error", "latency_ms": latency_ms, "error": str(exc)}

    def _check_qdrant(self) -> Dict[str, Any]:
        url = f"{self._qdrant_url}/healthz"
        start = time.perf_counter()
        try:
            resp = requests.get(url, timeout=10)
            latency_ms = int((time.perf_counter() - start) * 1000)
            if resp.status_code == 200:
                return {"status": "ok", "latency_ms": latency_ms}
            return {"status": "error", "latency_ms": latency_ms, "error": f"HTTP {resp.status_code}"}
        except (RequestException, OSError) as exc:
            latency_ms = int((time.perf_counter() - start) * 1000)
            logger.exception("Qdrant health check failed")
            return {"status": "error", "latency_ms": latency_ms, "error": str(exc)}

    def _check_mcp(self) -> Dict[str, Any]:
        url = f"{self._mcp_resource_url}/healthz"
        start = time.perf_counter()
        try:
            resp = requests.get(url, timeout=5)
            latency_ms = int((time.perf_counter() - start) * 1000)
            if resp.status_code == 200:
                payload = _safe_json(resp)
                return {
                    "status": "ok",
                    "latency_ms": latency_ms,
                    "url": self._mcp_resource_url,
                    "version": str(payload.get("version") or ""),
                }
            return {
                "status": "error",
                "latency_ms": latency_ms,
                "url": self._mcp_resource_url,
                "error": f"HTTP {resp.status_code}",
            }
        except (RequestException, OSError, ValueError) as exc:
            latency_ms = int((time.perf_counter() - start) * 1000)
            logger.exception("MCP health check failed")
            return {"status": "error", "latency_ms": latency_ms, "url": self._mcp_resource_url, "error": str(exc)}

    def check_broker(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "broker_url": _mask_broker_url(VALKEY_CONFIG),
            "valkey": {
                "address": VALKEY_ADDRESS,
                "port": int(VALKEY_PORT or 0),
                "ping_ok": False,
                "ping_response": None,
                "error": None,
            },
            "celery": {
                "broker_connect_ok": False,
                "broker_error": None,
                "worker_ping_ok": False,
                "workers": [],
                "worker_error": None,
            },
        }

        try:
            client = valkey.Valkey(
                host=str(VALKEY_ADDRESS or "localhost"),
                port=int(VALKEY_PORT or 6379),
                db=0,
                socket_timeout=1.5,
            )
            pong = client.ping()
            out["valkey"]["ping_ok"] = bool(pong)
            out["valkey"]["ping_response"] = str(pong)
        except (valkey.ValkeyError, OSError, ValueError) as exc:
            out["valkey"]["error"] = str(exc)

        try:
            with celery.connection_for_write() as conn:
                conn.ensure_connection(max_retries=0)
            out["celery"]["broker_connect_ok"] = True
        except (OSError, RuntimeError, ValueError) as exc:
            out["celery"]["broker_error"] = str(exc)

        try:
            inspector = celery.control.inspect(timeout=1.5)
            ping_map = inspector.ping() or {}
            workers = sorted(str(name) for name in ping_map.keys())
            out["celery"]["worker_ping_ok"] = bool(workers)
            out["celery"]["workers"] = workers
        except (AttributeError, OSError, RuntimeError, ValueError) as exc:
            out["celery"]["worker_error"] = str(exc)

        core_ok = bool(out["valkey"]["ping_ok"] and out["celery"]["broker_connect_ok"])
        workers_ok = bool(out["celery"]["worker_ping_ok"])
        out["ok"] = bool(core_ok and workers_ok)
        if out["ok"]:
            out["status"] = "ok"
        elif core_ok:
            out["status"] = "degraded"
        else:
            out["status"] = "error"
        return out

    def _check_flowforge(self) -> Dict[str, Any]:
        heartbeat = get_flowforge_worker_health()
        try:
            metrics = self._query_flowforge_operational_metrics()
        except (SQLAlchemyError, OSError, RuntimeError, ValueError) as exc:
            logger.exception("FlowForge health metrics failed")
            return {
                "status": "error",
                "worker": heartbeat,
                "error": str(exc),
                "metrics": {
                    "pending_notification_count": None,
                    "failed_notification_count": None,
                    "stuck_run_count": None,
                    "failed_run_count": None,
                },
            }

        issues: list[str] = []
        if not heartbeat.get("healthy"):
            issues.append(str(heartbeat.get("reason") or "FlowForge worker heartbeat is unhealthy."))
        if int(metrics.get("stuck_run_count") or 0) > 0:
            issues.append(f"{metrics['stuck_run_count']} workflow run(s) appear stuck.")
        if int(metrics.get("failed_run_count") or 0) > 0:
            issues.append(f"{metrics['failed_run_count']} workflow run(s) failed in the last 24 hours.")
        if int(metrics.get("failed_notification_count") or 0) > 0:
            issues.append(f"{metrics['failed_notification_count']} FlowForge notification side effect(s) failed.")

        return {
            "status": "ok" if not issues else "degraded",
            "worker": heartbeat,
            "metrics": metrics,
            "issues": issues,
        }

    def _query_flowforge_operational_metrics(self) -> Dict[str, Any]:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        rows = self._sql.execute_query_mappings(
            """
            SELECT
              (SELECT COUNT(*)
                 FROM flowforge_notifications
                WHERE status = 'pending') AS pending_notification_count,
              (SELECT COUNT(*)
                 FROM flowforge_notifications
                WHERE status = 'failed') AS failed_notification_count,
              (SELECT COUNT(*)
                 FROM flowforge_runs
                WHERE status IN ('queued', 'waiting', 'running')
                  AND updated_at <= :stuck_cutoff) AS stuck_run_count,
              (SELECT COUNT(*)
                 FROM flowforge_runs
                WHERE status = 'failed'
                  AND COALESCE(failed_at, updated_at, started_at) >= :failure_cutoff) AS failed_run_count
            """,
            {
                "stuck_cutoff": now - timedelta(minutes=30),
                "failure_cutoff": now - timedelta(hours=24),
            },
        )
        row = dict(rows[0]) if rows else {}
        return {
            "pending_notification_count": int(row.get("pending_notification_count") or 0),
            "failed_notification_count": int(row.get("failed_notification_count") or 0),
            "stuck_run_count": int(row.get("stuck_run_count") or 0),
            "failed_run_count": int(row.get("failed_run_count") or 0),
            "stuck_run_threshold_minutes": 30,
            "failed_run_window_hours": 24,
        }


def _safe_json(resp: requests.Response) -> Dict[str, Any]:
    try:
        payload = resp.json()
    except ValueError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _mask_broker_url(raw_url: str) -> str:
    text = str(raw_url or "").strip()
    if text == "":
        return ""
    try:
        parts = urlsplit(text)
        netloc = parts.netloc or ""
        if "@" not in netloc:
            return text
        creds, host_part = netloc.split("@", 1)
        if ":" in creds:
            user = creds.split(":", 1)[0]
            masked_creds = f"{user}:***"
        else:
            masked_creds = "***"
        return urlunsplit((parts.scheme, f"{masked_creds}@{host_part}", parts.path, parts.query, parts.fragment))
    except ValueError:
        return text
