from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional
from urllib.parse import urlsplit, urlunsplit

import requests
import valkey
from requests import RequestException
from sqlalchemy.exc import SQLAlchemyError

from app.celery_app import celery
from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.config import QDRANT_URL, VALKEY_ADDRESS, VALKEY_CONFIG, VALKEY_PORT, VLLM_BASE_URL, VLLM_MODEL
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
    ) -> None:
        self._sql = sql or ForgeMetaSQL()
        self._vllm_base_url = vllm_base_url or VLLM_BASE_URL
        self._vllm_model = vllm_model or VLLM_MODEL
        self._qdrant_url = qdrant_url or QDRANT_URL

    def check_all(self) -> Dict[str, Any]:
        checks: Dict[str, Any] = {}
        checks["app"] = self._check_app()
        checks["mysql"] = self._check_mysql()
        checks["vllm"] = self._check_vllm()
        checks["qdrant"] = self._check_qdrant()
        checks["broker"] = self.check_broker()

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

        out["ok"] = bool(out["valkey"]["ping_ok"] and out["celery"]["broker_connect_ok"])
        out["status"] = "ok" if out["ok"] else "error"
        return out


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
