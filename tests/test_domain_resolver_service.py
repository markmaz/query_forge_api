from __future__ import annotations

from app.services.domains.domain_resolver_service import DomainResolverService


class _StubSQL:
    def __init__(self, mapping_rows, uncovered_rows):
        self._mapping_rows = mapping_rows
        self._uncovered_rows = uncovered_rows

    def execute_query_mappings(self, query: str, params=None):
        if "FROM domain_workspace_table dwt" in query:
            return list(self._mapping_rows)
        if "LEFT JOIN domain_workspace_table" in query:
            return list(self._uncovered_rows)
        return []


def test_resolve_all_hits_mapped() -> None:
    mapping_rows = [
        {"domain_id": 10, "workspace_table_id": 1, "is_primary": 1, "domain_name": "Students"},
        {"domain_id": 10, "workspace_table_id": 2, "is_primary": 0, "domain_name": "Students"},
    ]
    svc = DomainResolverService(sql=_StubSQL(mapping_rows, []))
    result = svc.resolve_from_table_hits(
        workspace_id="ws1",
        table_hits=[
            {"workspace_table_id": 1, "score": 0.9},
            {"workspace_table_id": 2, "score": 0.5},
        ],
    )
    assert result["uncovered_tables"] == []
    assert result["recommended"][0]["coverage"] == 1.0


def test_resolve_missing_table_gap() -> None:
    mapping_rows = [
        {"domain_id": 10, "workspace_table_id": 1, "is_primary": 1, "domain_name": "Students"},
    ]
    uncovered_rows = [
        {"workspace_table_id": 2, "table_name": "dim_unmapped"},
    ]
    svc = DomainResolverService(sql=_StubSQL(mapping_rows, uncovered_rows))
    result = svc.resolve_from_table_hits(
        workspace_id="ws1",
        table_hits=[
            {"workspace_table_id": 1, "score": 0.9},
            {"workspace_table_id": 2, "score": 0.4},
        ],
    )
    assert result["recommended"][0]["coverage"] == 0.5
    assert result["uncovered_tables"][0]["workspace_table_id"] == 2


def test_resolve_split_hits_across_domains() -> None:
    mapping_rows = [
        {"domain_id": 10, "workspace_table_id": 1, "is_primary": 1, "domain_name": "Students"},
        {"domain_id": 10, "workspace_table_id": 2, "is_primary": 0, "domain_name": "Students"},
        {"domain_id": 11, "workspace_table_id": 3, "is_primary": 1, "domain_name": "Enrollment"},
    ]
    svc = DomainResolverService(sql=_StubSQL(mapping_rows, []))
    result = svc.resolve_from_table_hits(
        workspace_id="ws1",
        table_hits=[
            {"workspace_table_id": 1, "score": 0.9},
            {"workspace_table_id": 2, "score": 0.4},
            {"workspace_table_id": 3, "score": 0.8},
        ],
        max_domains=2,
    )
    assert result["recommended"][0]["domain_id"] == 10
    assert result["recommended"][1]["domain_id"] == 11
