from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import pytest

from app.exceptions.forge_error import ForgeError
from app.services.domain.domain_profile_metric_config_service import DomainProfileMetricConfigService


class _Tx:
    def __init__(self, parent: "_FakeSQL") -> None:
        self._parent = parent

    def __enter__(self) -> "_Tx":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        del exc_type, exc, tb
        return False

    def execute_write(self, query: str, params: Optional[Dict[str, Any]] = None) -> int:
        self._parent.execute_write(query, params)
        return 1


class _FakeSQL:
    def __init__(self, *, rows_by_call: List[List[Dict[str, Any]]]) -> None:
        self._rows_by_call = list(rows_by_call)
        self._call_index = 0
        self.last_write_query: Optional[str] = None
        self.last_write_params: Optional[Dict[str, Any]] = None

    def execute_query_mappings(self, query: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        del query, params
        if self._call_index >= len(self._rows_by_call):
            return []
        rows = self._rows_by_call[self._call_index]
        self._call_index += 1
        return [dict(row) for row in rows]

    def transaction(self) -> _Tx:
        return _Tx(self)

    def execute_write(self, query: str, params: Optional[Dict[str, Any]] = None) -> int:
        self.last_write_query = query
        self.last_write_params = dict(params or {})
        return 1


def _base_row(*, can_edit: int = 1, profile_id: Optional[int] = 5, metrics: Any = None) -> Dict[str, Any]:
    return {
        "domain_id": 3,
        "domain_name": "Sales Performance",
        "can_edit": can_edit,
        "profile_id": profile_id,
        "summary": "Sales summary",
        "keywords": json.dumps(["sales"]),
        "entities": json.dumps(["account"]),
        "metrics": metrics,
        "attributes": json.dumps(["territory_name"]),
        "synonyms": json.dumps([]),
        "acronyms": json.dumps([]),
        "notes": "notes",
    }


def test_get_profile_metrics_normalizes_string_entries() -> None:
    sql = _FakeSQL(rows_by_call=[[_base_row(metrics=json.dumps(["total_sales"]))]])
    svc = DomainProfileMetricConfigService(sql=sql)

    out = svc.get_profile_metrics(workspace_id="ws-1", user_id="user-1", domain_id=3)

    assert out["domain_id"] == 3
    assert out["metrics"]
    assert out["metrics"][0]["metric_key"] == "total_sales"
    assert out["metrics"][0]["agg"] == "sum"


def test_update_profile_metrics_updates_existing_profile() -> None:
    updated_metrics = [
        {
            "metric_key": "total_net_amount",
            "label": "Total Net Amount",
            "kind": "numeric",
            "agg": "sum",
            "column_key": "wt180.net_amount",
        }
    ]
    sql = _FakeSQL(
        rows_by_call=[
            [_base_row(metrics=json.dumps([]), profile_id=9)],
            [_base_row(metrics=json.dumps(updated_metrics), profile_id=9)],
        ]
    )
    svc = DomainProfileMetricConfigService(sql=sql)

    out = svc.update_profile_metrics(
        workspace_id="ws-1",
        user_id="user-1",
        domain_id=3,
        metrics_payload=updated_metrics,
    )

    assert out["metrics"][0]["metric_key"] == "total_net_amount"
    assert sql.last_write_query is not None
    assert "UPDATE domain_profile" in sql.last_write_query
    assert sql.last_write_params is not None
    assert json.loads(str(sql.last_write_params["metrics"]))[0]["metric_key"] == "total_net_amount"


def test_update_profile_metrics_requires_edit_permission() -> None:
    sql = _FakeSQL(rows_by_call=[[_base_row(can_edit=0, metrics=json.dumps([]), profile_id=9)]])
    svc = DomainProfileMetricConfigService(sql=sql)

    with pytest.raises(ForgeError) as exc_info:
        svc.update_profile_metrics(
            workspace_id="ws-1",
            user_id="user-1",
            domain_id=3,
            metrics_payload=[],
        )
    assert exc_info.value.status_code == 403
