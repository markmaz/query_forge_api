from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import pytest

from app.exceptions.forge_error import ForgeError
from app.services.metadata.gateway import MetadataGateway
from app.services.metadata.legacy_repository import LegacyMetadataRepository


@dataclass
class _WriteCall:
    query: str
    params: Any


class _FakeSQL:
    def __init__(self) -> None:
        self.query_responses: List[List[Dict[str, Any]]] = []
        self.write_calls: List[_WriteCall] = []

    def execute_query_mappings(self, query: str, params: Optional[Dict[str, Any]] = None):
        del query, params
        if not self.query_responses:
            return []
        return self.query_responses.pop(0)

    def execute_write(self, query: str, params: Any = None):
        self.write_calls.append(_WriteCall(query=query, params=params))
        if isinstance(params, list):
            return len(params)
        return 1

    @contextmanager
    def transaction(self):
        yield self


class _FakeWorkspaceRepo:
    def __init__(self, *, fail_on: Optional[str] = None) -> None:
        self.fail_on = fail_on
        self.calls: List[str] = []

    def _record(self, name: str):
        self.calls.append(name)
        if self.fail_on == name:
            raise RuntimeError(f"boom:{name}")

    def upsert_tables(self, **kwargs):
        del kwargs
        self._record("upsert_tables")
        return {"tables_upserted": 1}

    def upsert_columns(self, **kwargs):
        del kwargs
        self._record("upsert_columns")
        return {"columns_upserted": 1, "cols_by_table_id": {}}

    def mark_tables_missing(self, **kwargs):
        del kwargs
        self._record("mark_tables_missing")
        return 1

    def mark_columns_missing(self, **kwargs):
        del kwargs
        self._record("mark_columns_missing")
        return 1

    def get_table_by_name(self, **kwargs):
        del kwargs
        self._record("get_table_by_name")
        return None

    def get_table_by_id(self, **kwargs):
        del kwargs
        self._record("get_table_by_id")
        return None

    def list_tables(self, **kwargs):
        del kwargs
        self._record("list_tables")
        return []

    def get_column_by_name(self, **kwargs):
        del kwargs
        self._record("get_column_by_name")
        return None

    def patch_table_by_model_table_id(self, **kwargs):
        del kwargs
        self._record("patch_table_by_model_table_id")
        return 1

    def patch_column_by_model_column_id(self, **kwargs):
        del kwargs
        self._record("patch_column_by_model_column_id")
        return 1

    def patch_column_by_model_table_and_name(self, **kwargs):
        del kwargs
        self._record("patch_column_by_model_table_and_name")
        return 1

    def deactivate_columns_not_in(self, **kwargs):
        del kwargs
        self._record("deactivate_columns_not_in")
        return 1

    def clear_model_column_reference(self, **kwargs):
        del kwargs
        self._record("clear_model_column_reference")
        return 1

    def clear_model_table_reference(self, **kwargs):
        del kwargs
        self._record("clear_model_table_reference")
        return 1


def test_gateway_defaults_to_legacy_mode(monkeypatch):
    monkeypatch.setattr("app.services.metadata.gateway.METADATA_SOURCE_MODE", "legacy")
    gw = MetadataGateway(legacy_repo=LegacyMetadataRepository(sql=_FakeSQL()))
    assert gw.configured_mode == "legacy"
    assert gw.effective_mode == "legacy"


def test_gateway_dual_mode_reads_legacy_and_writes_workspace():
    sql = _FakeSQL()
    sql.query_responses.append(
        [
            {
                "id": 11,
                "name": "dim_student",
                "source_table_name": "dim_student",
                "description": "Students",
                "origin": "DBX",
                "is_missing_in_source": 0,
            }
        ]
    )
    workspace_repo = _FakeWorkspaceRepo()
    gw = MetadataGateway(
        mode="dual",
        legacy_repo=LegacyMetadataRepository(sql=sql),
        workspace_repo=workspace_repo,  # type: ignore[arg-type]
    )

    row = gw.get_table_by_name(table_name="dim_student")
    assert row is not None
    assert row.table_id == 11
    assert gw.configured_mode == "dual"
    assert gw.effective_mode == "dual"
    gw.upsert_tables(tables=[{"table_name": "dim_student"}], origin="DBX")
    assert "upsert_tables" in workspace_repo.calls


def test_gateway_invalid_mode_raises():
    with pytest.raises(ForgeError) as exc:
        MetadataGateway(mode="banana", legacy_repo=LegacyMetadataRepository(sql=_FakeSQL()))
    assert exc.value.status_code == 500


def test_legacy_repo_upsert_tables_returns_name_to_id():
    sql = _FakeSQL()
    sql.query_responses.append(
        [
            {"id": 10, "name": "dim_student"},
            {"id": 11, "name": "dim_school"},
        ]
    )
    repo = LegacyMetadataRepository(sql=sql)

    out = repo.upsert_tables(
        tables=[
            {"table_name": "dim_student", "description": "Students"},
            {"table_name": "dim_school", "description": "Schools"},
        ],
        origin="DBX",
    )

    assert out["tables_upserted"] == 2
    assert out["name_to_id"] == {"dim_student": 10, "dim_school": 11}
    assert len(sql.write_calls) == 1
    assert "INSERT INTO model_table" in sql.write_calls[0].query


def test_legacy_repo_upsert_columns_returns_counts_and_seen_sets():
    sql = _FakeSQL()
    repo = LegacyMetadataRepository(sql=sql)

    out = repo.upsert_columns(
        table_id_by_name={"dim_student": 10},
        columns=[
            {"table_name": "dim_student", "column_name": "first_name", "data_type": "string"},
            {"table_name": "dim_student", "column_name": "last_name", "data_type": "string"},
            {"table_name": "unknown", "column_name": "skip_me", "data_type": "string"},
        ],
        origin="DBX",
    )

    assert out["columns_upserted"] == 2
    assert out["cols_by_table_id"] == {10: ["first_name", "last_name"]}
    assert len(sql.write_calls) == 1
    assert "INSERT INTO model_column" in sql.write_calls[0].query


def test_gateway_workspace_mode_configured_but_effective_legacy():
    workspace_repo = _FakeWorkspaceRepo()
    gw = MetadataGateway(
        mode="workspace",
        legacy_repo=LegacyMetadataRepository(sql=_FakeSQL()),
        workspace_repo=workspace_repo,  # type: ignore[arg-type]
    )
    assert gw.configured_mode == "workspace"
    assert gw.effective_mode == "workspace"
    gw.list_tables()
    assert "list_tables" in workspace_repo.calls


def test_gateway_dual_mode_workspace_failure_does_not_break_legacy_write():
    sql = _FakeSQL()
    sql.query_responses.append([{"id": 10, "name": "dim_student"}])
    workspace_repo = _FakeWorkspaceRepo(fail_on="upsert_tables")
    gw = MetadataGateway(
        mode="dual",
        legacy_repo=LegacyMetadataRepository(sql=sql),
        workspace_repo=workspace_repo,  # type: ignore[arg-type]
    )

    out = gw.upsert_tables(tables=[{"table_name": "dim_student"}], origin="DBX")
    assert out["name_to_id"]["dim_student"] == 10
    assert len(sql.write_calls) == 1


def test_gateway_workspace_mode_workspace_failure_raises():
    workspace_repo = _FakeWorkspaceRepo(fail_on="patch_column_by_model_column_id")
    gw = MetadataGateway(
        mode="workspace",
        legacy_repo=LegacyMetadataRepository(sql=_FakeSQL()),
        workspace_repo=workspace_repo,  # type: ignore[arg-type]
    )

    with pytest.raises(ForgeError) as exc:
        gw.sync_column_patch_from_model(model_column_id=9, updates={"description": "x"})
    assert exc.value.status_code == 500
