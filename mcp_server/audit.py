from __future__ import annotations

import logging
from collections import Counter
from time import perf_counter
from typing import Any, Dict, Mapping, Optional, Protocol

from .context import RequestContext

logger = logging.getLogger(__name__)


class MCPAuditRepository(Protocol):
    def insert_event(self, payload: Dict[str, Any]): ...


class MCPAuditLogger:
    def __init__(self, *, enabled: bool = True, repository: MCPAuditRepository | None = None) -> None:
        self._enabled = bool(enabled)
        self._repository = repository
        self._counters: Counter[str] = Counter()

    def begin(self) -> float:
        return perf_counter()

    def emit(
        self,
        *,
        kind: str,
        name: str,
        request_context: Optional[RequestContext],
        request_summary: Mapping[str, Any],
        status: str,
        started_at: float,
        row_count: Optional[int] = None,
        error_code: Optional[str] = None,
        rate_limit_buckets: Optional[list[str]] = None,
    ) -> None:
        duration_ms = int((perf_counter() - started_at) * 1000)
        self._counters[f"{kind}:{name}:count"] += 1
        if error_code:
            self._counters[f"{kind}:{name}:error:{error_code}"] += 1
        if row_count is not None:
            self._counters[f"{kind}:{name}:rows"] += int(max(0, row_count))
        if not self._enabled:
            return
        self._persist_event(
            kind=kind,
            name=name,
            request_context=request_context,
            request_summary=request_summary,
            status=status,
            duration_ms=duration_ms,
            row_count=row_count,
            error_code=error_code,
            rate_limit_buckets=rate_limit_buckets or [],
        )
        logger.info(
            "mcp_audit kind=%s name=%s status=%s trace_id=%s user_id=%s workspace_id=%s duration_ms=%s row_count=%s error_code=%s request_summary=%s",
            kind,
            name,
            status,
            getattr(request_context, "trace_id", None),
            getattr(request_context, "user_id", None),
            getattr(request_context, "workspace_id", None),
            duration_ms,
            row_count,
            error_code,
            dict(request_summary or {}),
        )

    def snapshot(self) -> Dict[str, int]:
        return dict(self._counters)

    def _persist_event(
        self,
        *,
        kind: str,
        name: str,
        request_context: Optional[RequestContext],
        request_summary: Mapping[str, Any],
        status: str,
        duration_ms: int,
        row_count: Optional[int],
        error_code: Optional[str],
        rate_limit_buckets: list[str],
    ) -> None:
        repository = self._repository
        if repository is None:
            try:
                from app.repositories.mcp_oauth import MCPOAuthAuditRepository

                repository = MCPOAuthAuditRepository()
                self._repository = repository
            except Exception:
                logger.warning("mcp_audit_repository_unavailable", exc_info=True)
                return
        try:
            repository.insert_event(
                {
                    "event_type": f"mcp_{kind}_{'allowed' if status == 'ok' else 'denied'}",
                    "principal_type": getattr(request_context, "principal_type", None),
                    "principal_id": getattr(request_context, "principal_id", None),
                    "client_id": getattr(request_context, "client_id", None),
                    "workspace_id": getattr(request_context, "workspace_id", None)
                    or str(request_summary.get("workspace_id") or "").strip()
                    or None,
                    "requested_resource": None,
                    "requested_scopes": " ".join(getattr(request_context, "oauth_scopes", []) or []) or None,
                    "tool_name": name,
                    "domain_key": _extract_domain_key(request_summary),
                    "saved_query_id": _extract_saved_query_id(request_summary),
                    "decision": "allow" if status == "ok" else "deny",
                    "denial_reason": error_code,
                    "row_count_returned": row_count,
                    "rate_limit_bucket": ",".join(rate_limit_buckets) or None,
                    "trace_id": getattr(request_context, "trace_id", None),
                    "details_json": {
                        "kind": kind,
                        "duration_ms": duration_ms,
                        "request_summary": dict(request_summary or {}),
                    },
                }
            )
        except Exception:
            logger.warning("mcp_audit_persist_failed", exc_info=True)


def _extract_domain_key(request_summary: Mapping[str, Any]) -> str | None:
    direct = str(request_summary.get("domain_key") or "").strip()
    if direct:
        return direct
    plan = request_summary.get("plan")
    if isinstance(plan, Mapping):
        nested = str(plan.get("domain_key") or "").strip()
        return nested or None
    return None


def _extract_saved_query_id(request_summary: Mapping[str, Any]) -> str | None:
    return str(request_summary.get("query_id") or request_summary.get("saved_query_id") or "").strip() or None
