from __future__ import annotations

from app.repositories.mcp_oauth import MCPOAuthAuditRepository


class _SQL:
    def __init__(self) -> None:
        self.inserts = []

    def execute_insert(self, query, params=None):
        self.inserts.append((query, dict(params or {})))


def test_mcp_oauth_audit_repository_inserts_structured_event():
    sql = _SQL()
    repo = MCPOAuthAuditRepository(sql=sql)

    repo.insert_event(
        {
            "event_type": "mcp_tool_allowed",
            "principal_type": "user",
            "principal_id": "user-1",
            "client_id": "client-1",
            "workspace_id": "ws-1",
            "requested_resource": "https://mcp.query-forge.com",
            "requested_scopes": "qf:mcp:read",
            "tool_name": "search_domains",
            "domain_key": "students",
            "saved_query_id": None,
            "decision": "allow",
            "denial_reason": None,
            "row_count_returned": 3,
            "rate_limit_bucket": "mcp:user:user-1",
            "trace_id": "trace-1",
            "details_json": {"duration_ms": 12},
        }
    )

    query, params = sql.inserts[0]
    assert "INSERT INTO mcp_oauth_audit_log" in query
    assert params["event_type"] == "mcp_tool_allowed"
    assert params["principal_id"] == "user-1"
    assert params["details_json"] == '{"duration_ms":12}'
