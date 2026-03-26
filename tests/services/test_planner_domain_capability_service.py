from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, List, Optional

import pytest

from app.adapters.query_port import ForgeExecResult
from app.exceptions.forge_error import ForgeError
from app.services.domain.planner_domain_capability_service import PlannerDomainCapabilityService


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

    def execute_insert(self, query: str, params: Optional[Dict[str, Any]] = None) -> ForgeExecResult:
        return self._parent.execute_insert(query, params)


class _FakeSQL:
    def __init__(
        self,
        *,
        rows_by_call: List[List[Dict[str, Any]]],
        insert_results: Optional[List[ForgeExecResult]] = None,
    ) -> None:
        self._rows_by_call = list(rows_by_call)
        self._insert_results = list(insert_results or [])
        self._call_index = 0
        self.write_calls: List[Dict[str, Any]] = []

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
        self.write_calls.append({"query": query, "params": dict(params or {})})
        return 1

    def execute_insert(self, query: str, params: Optional[Dict[str, Any]] = None) -> ForgeExecResult:
        self.write_calls.append({"query": query, "params": dict(params or {})})
        if self._insert_results:
            return self._insert_results.pop(0)
        return ForgeExecResult(rowcount=1, lastrowid=1)


def _domain_row(*, domain_id: int, can_edit: int = 1) -> Dict[str, Any]:
    return {
        "domain_id": domain_id,
        "domain_name": "Student Enrollment",
        "can_edit": can_edit,
    }


def test_list_capabilities_returns_scope_sorted_rows() -> None:
    sql = _FakeSQL(
        rows_by_call=[
            [_domain_row(domain_id=9)],
            [
                {
                    "id": 1,
                    "scope_type": "vertical",
                    "scope_workspace_id": None,
                    "scope_vertical_norm": "education",
                    "base_domain_id": 9,
                    "capability_key": "SCHOOL_NAME",
                    "support_level": "direct",
                    "source_type": "semantic_concept",
                    "source_ref": "vertical-row",
                    "confidence": 0.6,
                    "notes": None,
                    "is_active": 1,
                },
                {
                    "id": 2,
                    "scope_type": "workspace_domain",
                    "scope_workspace_id": "ws-1",
                    "scope_vertical_norm": None,
                    "base_domain_id": 9,
                    "capability_key": "ENROLLMENT_STATUS",
                    "support_level": "direct",
                    "source_type": "dimension",
                    "source_ref": "workspace-row",
                    "confidence": 0.9,
                    "notes": None,
                    "is_active": 1,
                },
            ],
        ]
    )
    svc = PlannerDomainCapabilityService(sql=sql)
    out = svc.list_capabilities(
        workspace_id="ws-1",
        user_id="user-1",
        base_domain_id=9,
        vertical_norm="education",
        include_inactive=False,
    )

    assert out["domain_name"] == "Student Enrollment"
    assert [row["capability_key"] for row in out["capabilities"]] == ["ENROLLMENT_STATUS", "SCHOOL_NAME"]
    assert out["capabilities"][0]["is_inherited"] is False
    assert out["capabilities"][1]["is_inherited"] is True


def test_list_capabilities_normalizes_decimal_confidence() -> None:
    sql = _FakeSQL(
        rows_by_call=[
            [_domain_row(domain_id=9)],
            [
                {
                    "id": 1,
                    "scope_type": "workspace_domain",
                    "scope_workspace_id": "ws-1",
                    "scope_vertical_norm": None,
                    "base_domain_id": 9,
                    "capability_key": "SCHOOL_NAME",
                    "support_level": "direct",
                    "source_type": "semantic_concept",
                    "source_ref": "school_name",
                    "confidence": Decimal("0.9000"),
                    "notes": None,
                    "is_active": 1,
                }
            ],
        ]
    )
    svc = PlannerDomainCapabilityService(sql=sql)
    out = svc.list_capabilities(
        workspace_id="ws-1",
        user_id="user-1",
        base_domain_id=9,
        vertical_norm="generic",
        include_inactive=False,
    )

    assert out["capabilities"][0]["confidence"] == pytest.approx(0.9)
    assert isinstance(out["capabilities"][0]["confidence"], float)


def test_upsert_capability_rejects_workspace_scope_mismatch() -> None:
    svc = PlannerDomainCapabilityService(sql=_FakeSQL(rows_by_call=[]))
    with pytest.raises(ForgeError) as exc_info:
        svc.upsert_capability(
            workspace_id="ws-1",
            actor_user_id="user-1",
            payload={
                "scope_type": "workspace_domain",
                "scope_workspace_id": "ws-2",
                "base_domain_id": 9,
                "capability_key": "SCHOOL_NAME",
                "support_level": "direct",
                "source_type": "semantic_concept",
            },
        )
    assert exc_info.value.status_code == 400


def test_upsert_capability_inserts_new_row() -> None:
    sql = _FakeSQL(
        rows_by_call=[
            [_domain_row(domain_id=9)],
            [],
        ],
        insert_results=[ForgeExecResult(rowcount=1, lastrowid=14)],
    )
    svc = PlannerDomainCapabilityService(sql=sql)
    out = svc.upsert_capability(
        workspace_id="ws-1",
        actor_user_id="user-1",
        payload={
            "scope_type": "workspace_domain",
            "base_domain_id": 9,
            "capability_key": "SCHOOL_NAME",
            "support_level": "direct",
            "source_type": "semantic_concept",
            "source_ref": "RACE_ETHNICITY",
            "confidence": 0.9,
        },
    )

    assert out["capability_id"] == 14
    assert out["scope_workspace_id"] == "ws-1"
    assert sql.write_calls


def test_upsert_capability_insert_falls_back_to_select_when_lastrowid_missing() -> None:
    sql = _FakeSQL(
        rows_by_call=[
            [_domain_row(domain_id=9)],
            [],
            [{"id": 27}],
        ],
        insert_results=[ForgeExecResult(rowcount=1, lastrowid=None)],
    )
    svc = PlannerDomainCapabilityService(sql=sql)
    out = svc.upsert_capability(
        workspace_id="ws-1",
        actor_user_id="user-1",
        payload={
            "scope_type": "workspace_domain",
            "base_domain_id": 9,
            "capability_key": "SCHOOL_NAME",
            "support_level": "direct",
            "source_type": "semantic_concept",
            "source_ref": "school_name",
            "confidence": 0.9,
        },
    )

    assert out["capability_id"] == 27
