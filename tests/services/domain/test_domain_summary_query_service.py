from __future__ import annotations

from app.services.domain.summary.domain_summary_query_service import build_domain_summary_query


def test_build_domain_summary_query_sets_workspace_and_sample_size() -> None:
    query, params = build_domain_summary_query(workspace_id="ws1", sample_size=3)

    assert "domain_workspace_table" in query
    assert "workspace_table" in query
    assert params == {"ws": "ws1", "n": 3}
