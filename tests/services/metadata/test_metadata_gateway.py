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


def test_gateway_defaults_to_legacy_mode(monkeypatch):
    monkeypatch.setattr("app.services.metadata.gateway.METADATA_SOURCE_MODE", "legacy")
    gw = MetadataGateway(legacy_repo=LegacyMetadataRepository(sql=_FakeSQL()))
    assert gw.configured_mode == "legacy"
    assert gw.effective_mode == "legacy"


def test_gateway_dual_and_workspace_modes_currently_use_legacy_repo():
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
    gw = MetadataGateway(mode="dual", legacy_repo=LegacyMetadataRepository(sql=sql))

    row = gw.get_table_by_name(table_name="dim_student")
    assert row is not None
    assert row.table_id == 11
    assert gw.configured_mode == "dual"
    assert gw.effective_mode == "legacy"


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
    gw = MetadataGateway(mode="workspace", legacy_repo=LegacyMetadataRepository(sql=_FakeSQL()))
    assert gw.configured_mode == "workspace"
    assert gw.effective_mode == "legacy"
