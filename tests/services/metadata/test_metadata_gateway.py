from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List

import pytest

from app.services.metadata.gateway import MetadataGateway


@dataclass
class _Call:
    name: str
    kwargs: Dict[str, Any]


class _FakeWorkspaceRepo:
    def __init__(self) -> None:
        self.calls: List[_Call] = []

    def _record(self, name: str, **kwargs):
        self.calls.append(_Call(name=name, kwargs=dict(kwargs)))

    def get_table_by_name(self, **kwargs):
        self._record("get_table_by_name", **kwargs)
        return None

    def get_table_by_id(self, **kwargs):
        self._record("get_table_by_id", **kwargs)
        return None

    def list_tables(self, **kwargs):
        self._record("list_tables", **kwargs)
        return []

    def resolve_table_ids_by_names(self, *, names: Iterable[str]):
        clean = [str(name) for name in names]
        self._record("resolve_table_ids_by_names", names=clean)
        return {name: idx + 1 for idx, name in enumerate(clean)}

    def upsert_tables(self, **kwargs):
        self._record("upsert_tables", **kwargs)
        return {"tables_upserted": 1}

    def mark_tables_missing(self, **kwargs):
        self._record("mark_tables_missing", **kwargs)
        return 1

    def get_column_by_name(self, **kwargs):
        self._record("get_column_by_name", **kwargs)
        return None

    def upsert_columns(self, **kwargs):
        self._record("upsert_columns", **kwargs)
        return {"columns_upserted": 1, "cols_by_table_id": {}, "cols_by_table_name": {}}

    def mark_columns_missing(self, **kwargs):
        self._record("mark_columns_missing", **kwargs)
        return 1

    def patch_table_by_id(self, **kwargs):
        self._record("patch_table_by_id", **kwargs)
        return 1

    def patch_column_by_id(self, **kwargs):
        self._record("patch_column_by_id", **kwargs)
        return 1

    def patch_column_by_table_and_name(self, **kwargs):
        self._record("patch_column_by_table_and_name", **kwargs)
        return 1

    def deactivate_columns_not_in(self, **kwargs):
        self._record("deactivate_columns_not_in", **kwargs)
        return 1


def test_gateway_is_workspace_only() -> None:
    gw = MetadataGateway(workspace_repo=_FakeWorkspaceRepo())  # type: ignore[arg-type]
    assert gw.configured_mode == "workspace"
    assert gw.effective_mode == "workspace"


def test_gateway_preserves_legacy_configured_mode_while_using_workspace_behavior() -> None:
    gw = MetadataGateway(mode="legacy", workspace_repo=_FakeWorkspaceRepo())  # type: ignore[arg-type]

    assert gw.configured_mode == "legacy"
    assert gw.effective_mode == "workspace"


def test_gateway_rejects_unknown_metadata_mode() -> None:
    with pytest.raises(ValueError, match="Unsupported metadata_mode"):
        MetadataGateway(mode="future", workspace_repo=_FakeWorkspaceRepo())  # type: ignore[arg-type]


def test_gateway_upsert_tables_returns_workspace_name_to_id() -> None:
    repo = _FakeWorkspaceRepo()
    gw = MetadataGateway(workspace_repo=repo)  # type: ignore[arg-type]

    out = gw.upsert_tables(tables=[{"table_name": "dim_student"}], origin="DBX")

    assert out["tables_upserted"] == 1
    assert out["name_to_id"] == {"dim_student": 1}
    assert [call.name for call in repo.calls] == ["upsert_tables", "resolve_table_ids_by_names"]


def test_gateway_sync_column_profile_uses_workspace_column_id() -> None:
    repo = _FakeWorkspaceRepo()
    gw = MetadataGateway(workspace_repo=repo)  # type: ignore[arg-type]

    affected = gw.sync_column_profile(
        workspace_column_id=9,
        sample_values_json='["a"]',
        sample_stats_json='{"n":1}',
        sample_ran_at="2026-03-22T00:00:00Z",
        sample_error=None,
    )

    assert affected == 1
    assert repo.calls[-1].name == "patch_column_by_id"
    assert repo.calls[-1].kwargs["workspace_column_id"] == 9


def test_gateway_deactivate_columns_uses_workspace_table_id() -> None:
    repo = _FakeWorkspaceRepo()
    gw = MetadataGateway(workspace_repo=repo)  # type: ignore[arg-type]

    affected = gw.deactivate_workspace_columns_not_in(
        workspace_table_id=7,
        keep_column_names={"a", "b"},
        origin="DBX",
        only_not_missing=True,
    )

    assert affected == 1
    assert repo.calls[-1].name == "deactivate_columns_not_in"
    assert repo.calls[-1].kwargs["workspace_table_id"] == 7
