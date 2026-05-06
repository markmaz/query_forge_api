from __future__ import annotations

from typing import Any, Mapping

from .context import RequestContext
from .exceptions import MCPError

READ_SCOPE = "qf:mcp:read"
PLAN_SCOPE = "qf:mcp:plan"
PREVIEW_SCOPE = "qf:mcp:preview"

TOOL_SCOPES = {
    "search_domains": READ_SCOPE,
    "get_domain_profile": READ_SCOPE,
    "search_dictionary": READ_SCOPE,
    "list_saved_queries": READ_SCOPE,
    "plan_query": PLAN_SCOPE,
    "validate_query_plan": PLAN_SCOPE,
    "compile_query": PLAN_SCOPE,
    "preview_query": PREVIEW_SCOPE,
    "run_saved_query": PREVIEW_SCOPE,
}
PREVIEW_TOOLS = {"preview_query", "run_saved_query"}


def authorize_mcp_operation(
    *,
    kind: str,
    name: str,
    request_context: RequestContext,
    request_summary: Mapping[str, Any],
) -> None:
    required_scope = TOOL_SCOPES.get(name, READ_SCOPE if kind == "resource" else None)
    if required_scope and required_scope not in set(request_context.oauth_scopes):
        raise MCPError(
            error_code="FORBIDDEN",
            message=f"MCP operation requires OAuth scope {required_scope}",
            status_code=403,
        )

    if name in PREVIEW_TOOLS and not request_context.can_preview:
        raise MCPError(
            error_code="FORBIDDEN",
            message="MCP preview access is not granted for this principal",
            status_code=403,
        )

    if request_context.principal_type == "app":
        allowed_tools = {str(tool or "").strip() for tool in request_context.allowed_tools if str(tool or "").strip()}
        if allowed_tools and name not in allowed_tools:
            raise MCPError(
                error_code="FORBIDDEN",
                message=f"MCP tool '{name}' is not granted for this app principal",
                status_code=403,
            )

        domain_key = _extract_domain_key(request_summary)
        if domain_key:
            allowed_domains = {
                str(domain or "").strip().lower()
                for domain in request_context.allowed_domain_keys
                if str(domain or "").strip()
            }
            if domain_key.lower() not in allowed_domains:
                raise MCPError(
                    error_code="FORBIDDEN",
                    message="Domain is not granted for this app principal",
                    status_code=403,
                    details={"domain_key": domain_key},
                )


def _extract_domain_key(request_summary: Mapping[str, Any]) -> str | None:
    direct = str(request_summary.get("domain_key") or "").strip()
    if direct:
        return direct
    plan = request_summary.get("plan")
    if isinstance(plan, Mapping):
        nested = str(plan.get("domain_key") or "").strip()
        if nested:
            return nested
    return None


__all__ = ["authorize_mcp_operation"]
