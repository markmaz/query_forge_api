from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import pytest

from app.exceptions.forge_error import ForgeError
from app.services.domain.domain_time_policy_service import DomainTimePolicyService


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


def _base_row(
    *,
    can_edit: int = 1,
    policy_id: Optional[int] = 11,
    relative_map: Any = None,
) -> Dict[str, Any]:
    return {
        "domain_id": 3,
        "domain_name": "Sales Performance",
        "can_edit": can_edit,
        "policy_id": policy_id,
        "calendar_mode": "fiscal" if policy_id else None,
        "fiscal_year_start_month": 7 if policy_id else None,
        "school_year_start_month": 8 if policy_id else None,
        "school_year_end_month": 5 if policy_id else None,
        "timezone": "America/Chicago" if policy_id else None,
        "week_start": "monday" if policy_id else None,
        "default_time_concept_key": "ORDER_DATE" if policy_id else None,
        "allow_relative_ranges": 1 if policy_id else None,
        "default_grain": "quarter" if policy_id else None,
        "prefer_time_object_over_filter": 1 if policy_id else None,
        "strict_mode": 1 if policy_id else None,
        "relative_map": relative_map if policy_id else None,
        "notes": "policy note" if policy_id else None,
    }


def test_get_policy_returns_defaults_when_missing() -> None:
    sql = _FakeSQL(rows_by_call=[[_base_row(policy_id=None)]])
    svc = DomainTimePolicyService(sql=sql)
    out = svc.get_policy(workspace_id="ws-1", user_id="user-1", domain_id=3)
    assert out["has_policy"] is False
    assert out["policy"]["calendar_mode"] == "calendar"
    assert out["policy"]["relative_map"] == {}


def test_update_policy_updates_existing_policy() -> None:
    updated_rel = {"this_quarter": "current_fiscal_quarter"}
    sql = _FakeSQL(
        rows_by_call=[
            [_base_row(policy_id=11, relative_map=json.dumps({}))],
            [_base_row(policy_id=11, relative_map=json.dumps(updated_rel))],
        ]
    )
    svc = DomainTimePolicyService(sql=sql)
    out = svc.update_policy(
        workspace_id="ws-1",
        user_id="user-1",
        domain_id=3,
        policy_payload={"relative_map": updated_rel, "default_grain": "quarter"},
    )
    assert out["policy"]["default_grain"] == "quarter"
    assert out["policy"]["relative_map"]["this_quarter"] == "current_fiscal_quarter"
    assert sql.last_write_query is not None
    assert "UPDATE domain_time_policy" in sql.last_write_query


def test_update_policy_validation_error() -> None:
    sql = _FakeSQL(rows_by_call=[[_base_row(policy_id=11)]])
    svc = DomainTimePolicyService(sql=sql)
    with pytest.raises(ForgeError) as exc_info:
        svc.update_policy(
            workspace_id="ws-1",
            user_id="user-1",
            domain_id=3,
            policy_payload={"calendar_mode": "bad"},
        )
    assert exc_info.value.status_code == 400


def test_update_policy_accepts_school_year_mode() -> None:
    sql = _FakeSQL(
        rows_by_call=[
            [_base_row(policy_id=11, relative_map=json.dumps({}))],
            [[{**_base_row(policy_id=11, relative_map=json.dumps({})), "calendar_mode": "school_year"}][0]],
        ]
    )
    svc = DomainTimePolicyService(sql=sql)
    out = svc.update_policy(
        workspace_id="ws-1",
        user_id="user-1",
        domain_id=3,
        policy_payload={
            "calendar_mode": "school_year",
            "school_year_start_month": 8,
            "school_year_end_month": 5,
        },
    )
    assert out["policy"]["calendar_mode"] == "school_year"
    assert sql.last_write_params is not None
    assert sql.last_write_params["school_year_start_month"] == 8
    assert sql.last_write_params["school_year_end_month"] == 5


def test_update_policy_requires_edit_permission() -> None:
    sql = _FakeSQL(rows_by_call=[[_base_row(can_edit=0, policy_id=11)]])
    svc = DomainTimePolicyService(sql=sql)
    with pytest.raises(ForgeError) as exc_info:
        svc.update_policy(
            workspace_id="ws-1",
            user_id="user-1",
            domain_id=3,
            policy_payload={"calendar_mode": "calendar"},
        )
    assert exc_info.value.status_code == 403
