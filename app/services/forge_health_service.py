"""
app/services/forge_health_service.py

QueryForge infrastructure health checks.

Used by /api/v1/health (deep) to verify connectivity to all
required backend services: MySQL meta-DB, Valkey cache,
Qdrant vector DB, and the workspace LLM configuration.

Each check is independent — failures in one service do not
prevent the others from being reported.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class ForgeServiceCheck:
    name: str
    ok: bool
    latency_ms: Optional[float] = None
    detail: Optional[str] = None


@dataclass
class ForgeHealthReport:
    checks: List[ForgeServiceCheck] = field(default_factory=list)

    @property
    def healthy(self) -> bool:
        return all(c.ok for c in self.checks)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "healthy": self.healthy,
            "checks": [
                {
                    "name": c.name,
                    "ok": c.ok,
                    "latency_ms": round(c.latency_ms, 1) if c.latency_ms is not None else None,
                    "detail": c.detail,
                }
                for c in self.checks
            ],
        }


class ForgeHealthService:
    """
    Runs lightweight connectivity probes for QF infrastructure components.
    All probes time out quickly — this endpoint must stay fast.
    """

    PROBE_TIMEOUT_S: float = 2.0

    def run(self, *, workspace_id: Optional[str] = None) -> ForgeHealthReport:
        report = ForgeHealthReport()
        report.checks.append(self._check_meta_db())
        report.checks.append(self._check_valkey())
        report.checks.append(self._check_vector_db())
        if workspace_id:
            report.checks.append(self._check_workspace_llm(workspace_id))
        return report

    # ------------------------------------------------------------------
    # Individual probes
    # ------------------------------------------------------------------

    def _check_meta_db(self) -> ForgeServiceCheck:
        name = "meta_db"
        try:
            from app.adapters.mysql_sql_executor import execute_query_mappings
            t0 = time.monotonic()
            execute_query_mappings("SELECT 1 AS ping", {})
            latency_ms = (time.monotonic() - t0) * 1000
            return ForgeServiceCheck(name=name, ok=True, latency_ms=latency_ms)
        except Exception as exc:
            logger.warning("forge_health meta_db probe failed: %s", exc)
            return ForgeServiceCheck(name=name, ok=False, detail=str(exc)[:120])

    def _check_valkey(self) -> ForgeServiceCheck:
        name = "valkey"
        try:
            import valkey
            from app.config import VALKEY_ADDRESS, VALKEY_PORT
            t0 = time.monotonic()
            client = valkey.Valkey(
                host=str(VALKEY_ADDRESS or "localhost"),
                port=int(VALKEY_PORT or 6379),
                db=0,
                socket_timeout=self.PROBE_TIMEOUT_S,
            )
            client.ping()
            latency_ms = (time.monotonic() - t0) * 1000
            return ForgeServiceCheck(name=name, ok=True, latency_ms=latency_ms)
        except Exception as exc:
            logger.warning("forge_health valkey probe failed: %s", exc)
            return ForgeServiceCheck(name=name, ok=False, detail=str(exc)[:120])

    def _check_vector_db(self) -> ForgeServiceCheck:
        name = "vector_db"
        try:
            from qdrant_client import QdrantClient
            from app.config import QDRANT_HOST, QDRANT_PORT
            t0 = time.monotonic()
            qc = QdrantClient(
                host=str(QDRANT_HOST or "localhost"),
                port=int(QDRANT_PORT or 6333),
                timeout=self.PROBE_TIMEOUT_S,
            )
            qc.get_collections()
            latency_ms = (time.monotonic() - t0) * 1000
            return ForgeServiceCheck(name=name, ok=True, latency_ms=latency_ms)
        except Exception as exc:
            logger.warning("forge_health vector_db probe failed: %s", exc)
            return ForgeServiceCheck(name=name, ok=False, detail=str(exc)[:120])

    def _check_workspace_llm(self, workspace_id: str) -> ForgeServiceCheck:
        name = "workspace_llm"
        try:
            from app.services.tenancy.workspace_llm_service import WorkspaceLLMService
            t0 = time.monotonic()
            llm = WorkspaceLLMService().get_llm_for_role(workspace_id, "default")
            latency_ms = (time.monotonic() - t0) * 1000
            if llm is None:
                return ForgeServiceCheck(name=name, ok=False, latency_ms=latency_ms, detail="No LLM configured")
            return ForgeServiceCheck(name=name, ok=True, latency_ms=latency_ms)
        except Exception as exc:
            logger.warning("forge_health llm probe failed for workspace %s: %s", workspace_id, exc)
            return ForgeServiceCheck(name=name, ok=False, detail=str(exc)[:120])
