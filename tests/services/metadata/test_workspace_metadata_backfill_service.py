from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import pytest

from app.exceptions.forge_error import ForgeError
from app.services.metadata.workspace_metadata_backfill_service import WorkspaceMetadataBackfillService


@dataclass
class _WriteCall:
    tag: str
    params: Any


class _FakeSQL:
    def __init__(self) -> None:
        self.query_by_tag: Dict[str, List[List[Dict[str, Any]]]] = {}
        self.write_result_by_tag: Dict[str, int] = {}
        self.write_calls: List[_WriteCall] = []
        self.query_params_by_tag: Dict[str, List[Dict[str, Any]]] = {}

    def execute_query_mappings(self, query: str, params: Optional[Dict[str, Any]] = None):
        tag = _extract_tag(query)
        self.query_params_by_tag.setdefault(tag, []).append(dict(params or {}))
        queue = self.query_by_tag.get(tag, [])
        if not queue:
            return []
        return queue.pop(0)

    def execute_write(self, query: str, params: Any = None):
        tag = _extract_tag(query)
        self.write_calls.append(_WriteCall(tag=tag, params=params))
        return int(self.write_result_by_tag.get(tag, 0))

    @contextmanager
    def transaction(self):
        yield self


def _extract_tag(query: str) -> str:
    marker = "qf_backfill:"
    idx = query.find(marker)
    if idx < 0:
        return "unknown"
    tail = query[idx + len(marker) :]
    return tail.split("*/", 1)[0].strip()


def _seed_dry_run_sql() -> _FakeSQL:
    sql = _FakeSQL()
    sql.query_by_tag = {
        "table_scope_counts": [[{"workspace_table_rows": 5, "matched_model_table_rows": 4, "missing_model_table_rows": 1}]],
        "table_mismatch_count": [[{"mismatch_count": 2}]],
        "table_mismatch_samples": [[{"workspace_table_id": 11}, {"workspace_table_id": 12}]],
        "column_scope_counts": [[{"workspace_column_rows": 20, "matched_model_column_rows": 17, "missing_model_column_rows": 3}]],
        "column_conflict_samples": [[{"workspace_column_id": 999, "match_count": 2}]],
        "column_mismatch_count": [[{"mismatch_count": 4}]],
        "column_mismatch_samples": [[{"workspace_column_id": 101}, {"workspace_column_id": 102}]],
    }
    return sql


def test_backfill_dry_run_reports_without_updates():
    sql = _seed_dry_run_sql()
    svc = WorkspaceMetadataBackfillService(sql=sql)

    out = svc.run(workspace_id="ws-1", dry_run=True, sample_limit=10)

    assert out["workspace_id"] == "ws-1"
    assert out["dry_run"] is True
    assert out["tables"]["workspace_table_rows"] == 5
    assert out["tables"]["would_update_rows"] == 2
    assert out["tables"]["updated_rows"] == 0
    assert out["columns"]["workspace_column_rows"] == 20
    assert out["columns"]["would_update_rows"] == 4
    assert out["columns"]["updated_rows"] == 0
    assert out["conflicts"]["count"] == 1
    assert out["conflicts"]["case_insensitive_column_match_conflicts"][0]["workspace_column_id"] == 999
    assert not sql.write_calls


def test_backfill_live_updates_when_mismatches_exist():
    sql = _seed_dry_run_sql()
    sql.write_result_by_tag = {
        "table_update": 2,
        "column_update": 4,
    }
    svc = WorkspaceMetadataBackfillService(sql=sql)

    out = svc.run(workspace_id="ws-1", dry_run=False, sample_limit=10)

    assert out["dry_run"] is False
    assert out["tables"]["updated_rows"] == 2
    assert out["columns"]["updated_rows"] == 4
    assert [call.tag for call in sql.write_calls] == ["table_update", "column_update"]


def test_backfill_live_idempotent_when_no_mismatches():
    sql = _FakeSQL()
    sql.query_by_tag = {
        "table_scope_counts": [[{"workspace_table_rows": 5, "matched_model_table_rows": 5, "missing_model_table_rows": 0}]],
        "table_mismatch_count": [[{"mismatch_count": 0}]],
        "table_mismatch_samples": [[]],
        "column_scope_counts": [[{"workspace_column_rows": 20, "matched_model_column_rows": 20, "missing_model_column_rows": 0}]],
        "column_conflict_samples": [[]],
        "column_mismatch_count": [[{"mismatch_count": 0}]],
        "column_mismatch_samples": [[]],
    }
    svc = WorkspaceMetadataBackfillService(sql=sql)

    out = svc.run(workspace_id="ws-1", dry_run=False, sample_limit=10)

    assert out["tables"]["would_update_rows"] == 0
    assert out["tables"]["updated_rows"] == 0
    assert out["columns"]["would_update_rows"] == 0
    assert out["columns"]["updated_rows"] == 0
    assert not sql.write_calls


def test_backfill_passes_workspace_scope_params_to_queries():
    sql = _seed_dry_run_sql()
    svc = WorkspaceMetadataBackfillService(sql=sql)

    svc.run(workspace_id="scope-abc", dry_run=True, sample_limit=7)

    for tag, calls in sql.query_params_by_tag.items():
        assert calls, f"expected params for {tag}"
        for params in calls:
            assert params["workspace_id"] == "scope-abc"
            if "sample" in tag:
                assert params["sample_limit"] == 7


def test_backfill_wraps_unexpected_errors():
    class _BoomSQL(_FakeSQL):
        def execute_query_mappings(self, query: str, params: Optional[Dict[str, Any]] = None):
            raise RuntimeError("db exploded")

    svc = WorkspaceMetadataBackfillService(sql=_BoomSQL())

    with pytest.raises(ForgeError) as exc:
        svc.run(workspace_id="ws-1", dry_run=True)

    assert exc.value.status_code == 500
    assert "workspace metadata backfill failed" in str(exc.value)
