from __future__ import annotations

import json
from typing import Any, Dict, Optional

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.ports.sql_executor import ForgeExecResult, ForgeQueryPort


def _json_or_none(value: Any) -> Optional[str]:
    if value is None:
        return None
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


class MCPOAuthAuditRepository:
    def __init__(self, *, sql: Optional[ForgeQueryPort] = None) -> None:
        self._sql = sql or ForgeMetaSQL()

    def insert_event(self, payload: Dict[str, Any]) -> ForgeExecResult:
        params = dict(payload)
        params["details_json"] = _json_or_none(params.get("details_json"))
        return self._sql.execute_insert(
            """
            INSERT INTO mcp_oauth_audit_log (
              event_type,
              principal_type,
              principal_id,
              client_id,
              workspace_id,
              requested_resource,
              requested_scopes,
              tool_name,
              domain_key,
              saved_query_id,
              decision,
              denial_reason,
              row_count_returned,
              rate_limit_bucket,
              trace_id,
              details_json
            ) VALUES (
              :event_type,
              :principal_type,
              :principal_id,
              :client_id,
              :workspace_id,
              :requested_resource,
              :requested_scopes,
              :tool_name,
              :domain_key,
              :saved_query_id,
              :decision,
              :denial_reason,
              :row_count_returned,
              :rate_limit_bucket,
              :trace_id,
              :details_json
            )
            """,
            params,
        )


__all__ = ["MCPOAuthAuditRepository"]
