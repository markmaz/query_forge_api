from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional

import requests

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.config import QDRANT_URL, VLLM_BASE_URL, VLLM_MODEL
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
        except Exception as exc:
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
        except Exception as exc:
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
        except Exception as exc:
            latency_ms = int((time.perf_counter() - start) * 1000)
            logger.exception("Qdrant health check failed")
            return {"status": "error", "latency_ms": latency_ms, "error": str(exc)}
