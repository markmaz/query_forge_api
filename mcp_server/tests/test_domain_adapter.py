from __future__ import annotations

from types import SimpleNamespace

from mcp_server.adapters.domain_adapter import DomainAdapter
from mcp_server.context import RequestContext


def _request_context() -> RequestContext:
    return RequestContext(
        user_id="user-1",
        workspace_id="ws-1",
        allowed_domain_keys=["students", "schools"],
        can_preview=True,
        can_run_saved_queries=True,
        trace_id="trace-1",
        effective_roles=["query_studio:user"],
        is_admin=False,
    )


def test_search_domains_filters_to_visible_vector_hits():
    adapter = DomainAdapter(
        explorer_service=SimpleNamespace(
            list_domains=lambda workspace_id, user_id: [
                {"id": 1, "key": "students", "label": "Students", "description": "Student roster"},
                {"id": 2, "key": "schools", "label": "Schools", "description": "School catalog"},
            ],
            get_domain_explorer=lambda **kwargs: {},
        ),
        profile_service=SimpleNamespace(get_profile=lambda workspace_id, domain_id: {}),
        capabilities_service=SimpleNamespace(
            get_domain_capabilities=lambda workspace_id, user_id, domain_id: {
                "dimensions": [{"column_key": "wt1.school_name"}],
                "domain_metrics": [{"metric_key": "enrollment"}] if domain_id == 1 else [],
                "time_columns": [{"column_key": "wt1.calendar_date"}] if domain_id == 1 else [],
            }
        ),
        vector_index_service=SimpleNamespace(
            search_domains=lambda workspace_id, query, limit: {
                "results": [
                    {"domain_id": 999, "score": 0.99},
                    {"domain_id": 1, "score": 0.88, "summary": "Student metrics"},
                ]
            }
        ),
    )

    response = adapter.search_domains(
        request_context=_request_context(),
        query="student enrollment",
        limit=5,
    )

    assert [item.domain_key for item in response.domains] == ["students"]
    assert response.domains[0].capabilities.supports_aggregate is True
    assert response.domains[0].capabilities.supports_time_filtering is True


def test_get_domain_profile_returns_planner_safe_summary():
    adapter = DomainAdapter(
        explorer_service=SimpleNamespace(
            list_domains=lambda workspace_id, user_id: [
                {"id": 1, "key": "students", "label": "Students", "description": "Student roster"},
            ],
            get_domain_explorer=lambda workspace_id, user_id, domain_id: {
                "recommendedFields": [
                    {"columnKey": "wt1.student_name", "label": "Student Name"},
                    {"columnKey": "wt1.school_name", "label": "School Name"},
                ]
            },
        ),
        profile_service=SimpleNamespace(
            get_profile=lambda workspace_id, domain_id: {
                "summary": "One row per student",
                "notes": "Current enrollment snapshot",
                "entities": [{"label": "Student"}],
            }
        ),
        capabilities_service=SimpleNamespace(
            get_domain_capabilities=lambda workspace_id, user_id, domain_id: {
                "domain_metrics": [{"metric_key": "enrollment", "label": "Enrollment"}],
                "time_columns": [{"column_key": "wt1.calendar_date"}],
            }
        ),
        vector_index_service=SimpleNamespace(search_domains=lambda **kwargs: {"results": []}),
    )

    response = adapter.get_domain_profile(
        request_context=_request_context(),
        domain_key="students",
    )

    assert response.domain_key == "students"
    assert response.supported_intents == ["listing", "aggregate", "trend"]
    assert response.primary_entities == ["Student"]
    assert response.recommended_metrics[0].key == "enrollment"
    assert response.recommended_dimensions[0].key == "wt1.student_name"
