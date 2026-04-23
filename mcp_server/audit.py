from __future__ import annotations

import logging
from collections import Counter
from time import perf_counter
from typing import Any, Dict, Mapping, Optional

from .context import RequestContext

logger = logging.getLogger(__name__)


class MCPAuditLogger:
    def __init__(self, *, enabled: bool = True) -> None:
        self._enabled = bool(enabled)
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
    ) -> None:
        duration_ms = int((perf_counter() - started_at) * 1000)
        self._counters[f"{kind}:{name}:count"] += 1
        if error_code:
            self._counters[f"{kind}:{name}:error:{error_code}"] += 1
        if row_count is not None:
            self._counters[f"{kind}:{name}:rows"] += int(max(0, row_count))
        if not self._enabled:
            return
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
