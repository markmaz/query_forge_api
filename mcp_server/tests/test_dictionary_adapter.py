from __future__ import annotations

from types import SimpleNamespace

from mcp_server.adapters.dictionary_adapter import DictionaryAdapter
from mcp_server.context import RequestContext


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


def test_search_dictionary_constrains_to_domain_capabilities():
    domain_adapter = SimpleNamespace(
        resolve_domain=lambda request_context, domain_key: {"id": 1, "key": "students"},
        list_visible_domains=lambda request_context: [{"id": 1, "key": "students"}],
    )
    capabilities = {
        "dimensions": [
            {
                "column_key": "wt12.school_name",
                "label": "School Name",
                "filterable": True,
                "table_name": "dim_school",
                "semantic_type": "school",
            }
        ],
        "domain_metrics": [{"metric_key": "enrollment", "label": "Enrollment", "kind": "count"}],
    }
    adapter = DictionaryAdapter(
        dictionary_service=SimpleNamespace(
            search_columns=lambda workspace_id, q, limit, active_only: {
                "rows": [
                    {"workspace_table_id": 12, "column_name": "school_name", "table_name": "dim_school"},
                    {"workspace_table_id": 77, "column_name": "secret_field", "table_name": "dim_hidden"},
                ]
            }
        ),
        capabilities_service=SimpleNamespace(
            get_domain_capabilities=lambda workspace_id, user_id, domain_id: capabilities
        ),
        domain_adapter=domain_adapter,
    )

    response = adapter.search_dictionary(
        request_context=_request_context(),
        query="school enrollment",
        domain_key="students",
        types=["column", "metric", "filter"],
        limit=10,
    )

    keys = [item.key for item in response.results]
    assert "wt12.school_name" in keys
    assert "enrollment" in keys
    assert "wt77.secret_field" not in keys
    assert all(item.domain_key == "students" for item in response.results)
