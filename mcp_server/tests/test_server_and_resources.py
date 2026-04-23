from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

from mcp_server.config import MCPSettings
from mcp_server.context import RequestContext
from mcp_server.dependencies import MCPDependencies
from mcp_server.resources.semantic_registry import SemanticRegistryResource
from mcp_server.server import create_mcp_server


def _request_context() -> RequestContext:
    return RequestContext(
        user_id="user-1",
        workspace_id="ws-1",
        allowed_domain_keys=["students"],
        can_preview=True,
        can_run_saved_queries=True,
        trace_id="trace-1",
        effective_roles=["query_studio:user"],
        is_admin=False,
    )


def test_create_mcp_server_registers_expected_tools():
    deps = MCPDependencies(
        settings=MCPSettings(enable_resources=True),
        auth_resolver=lambda workspace_id, ctx: _request_context(),
        domain_adapter_factory=lambda: SimpleNamespace(
            search_domains=lambda **kwargs: {"domains": []},
            get_domain_profile=lambda **kwargs: {"domain_key": "students"},
            domains_resource=lambda **kwargs: {"workspace_id": "ws-1", "domains": []},
        ),
        dictionary_adapter_factory=lambda: SimpleNamespace(search_dictionary=lambda **kwargs: {"results": []}),
        planner_adapter_factory=lambda: SimpleNamespace(
            plan_query=lambda **kwargs: {"status": "ok"},
            validate_query_plan=lambda **kwargs: {"valid": True, "errors": [], "warnings": [], "normalized_plan": kwargs["plan"].model_dump(mode="json")},
            compile_query=lambda **kwargs: {"sql_json": {}, "compiled": {}, "execution_metadata": {"row_limit": 100, "timeout_seconds": 30}},
            preview_query=lambda **kwargs: {"columns": [], "rows": [], "truncated": False, "row_count_returned": 0},
        ),
        saved_query_adapter_factory=lambda: SimpleNamespace(
            list_saved_queries=lambda **kwargs: {"items": []},
            run_saved_query=lambda **kwargs: {"query_id": "q1", "columns": [], "rows": [], "truncated": False},
            saved_queries_resource=lambda **kwargs: {"workspace_id": "ws-1", "items": []},
        ),
        policy_resource_factory=lambda: SimpleNamespace(summary=lambda workspace_id: {"workspace_id": workspace_id, "families": []}),
        semantic_resource_factory=lambda: SimpleNamespace(summary=lambda concept_key: {"concept_key": concept_key, "aliases": []}),
    )

    mcp = create_mcp_server(settings=MCPSettings(enable_resources=True), dependencies=deps)
    tools = asyncio.run(mcp.list_tools())
    tool_names = {tool.name for tool in tools}

    assert tool_names == {
        "search_domains",
        "get_domain_profile",
        "search_dictionary",
        "plan_query",
        "validate_query_plan",
        "compile_query",
        "preview_query",
        "list_saved_queries",
        "run_saved_query",
    }


def test_semantic_registry_resource_returns_alias_summary():
    resource = SemanticRegistryResource(
        concept_service=SimpleNamespace(
            list_concepts=lambda q, page, page_size: {
                "rows": [
                    {
                        "concept_key": "STUDENT_NAME",
                        "name": "Student Name",
                        "description": "Preferred student name",
                        "semantic_type": "name",
                        "entity": "student",
                    }
                ]
            },
            list_aliases=lambda concept_key: {"rows": [{"alias_key": "student_display_name"}]},
        )
    )

    payload = resource.summary(concept_key="student_name")

    assert payload["concept_key"] == "STUDENT_NAME"
    assert payload["aliases"] == ["student_display_name"]
