from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import pytest

from app.adapters.query_port import ForgeExecResult
from app.exceptions.forge_error import ForgeError
import app.services.domain.planner_rerank_policy_service as planner_rerank_policy_service
from app.services.domain.planner_rerank_policy_service import PlannerRerankPolicyService


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


def _policy_row(*, id: int, policy_key: str, scope_type: str, priority: int = 100):
    return {
        "id": id,
        "policy_key": policy_key,
        "name": policy_key.replace("_", " ").title(),
        "description": None,
        "scope_type": scope_type,
        "scope_workspace_id": "ws-1" if "workspace" in scope_type else None,
        "scope_vertical_norm": "education" if "vertical" in scope_type else None,
        "scope_base_domain_id": 9 if scope_type.endswith("_domain") else None,
        "priority": priority,
        "is_active": 1,
        "stop_on_match": 0,
        "policy_json": json.dumps(
            {
                "version": 1,
                "when_signals_all": ["student_listing"],
                "prefer_capabilities": ["STUDENT_IDENTITY"],
                "boost": 0.2,
                "penalty": 0.0,
                "max_effect": 0.2,
            }
        ),
    }


def _domain_row(*, domain_id: int, domain_name: str = "Enrollment") -> Dict[str, Any]:
    return {
        "domain_id": domain_id,
        "domain_name": domain_name,
        "can_edit": 1,
    }


def test_get_applicable_policies_orders_by_scope_then_priority() -> None:
    sql = _FakeSQL(
        rows_by_call=[
            [
                _policy_row(id=1, policy_key="global_rule", scope_type="global", priority=200),
                _policy_row(id=2, policy_key="workspace_rule", scope_type="workspace", priority=200),
                _policy_row(id=3, policy_key="workspace_domain_rule", scope_type="workspace_domain", priority=300),
                _policy_row(id=4, policy_key="vertical_rule", scope_type="vertical", priority=100),
            ]
        ]
    )
    svc = PlannerRerankPolicyService(sql=sql)
    out = svc.get_applicable_policies(workspace_id="ws-1", vertical_norm="education", base_domain_id=9)
    assert [row["policy_key"] for row in out] == [
        "workspace_domain_rule",
        "workspace_rule",
        "vertical_rule",
        "global_rule",
    ]


def test_list_policies_includes_domain_context_and_inherited_flags() -> None:
    sql = _FakeSQL(
        rows_by_call=[
            [_domain_row(domain_id=9, domain_name="Student Enrollment")],
            [
                _policy_row(id=1, policy_key="global_rule", scope_type="global", priority=200),
                _policy_row(id=2, policy_key="workspace_domain_rule", scope_type="workspace_domain", priority=150),
            ],
        ]
    )
    svc = PlannerRerankPolicyService(sql=sql)
    out = svc.list_policies(
        workspace_id="ws-1",
        user_id="user-1",
        base_domain_id=9,
        vertical_norm="education",
        include_inactive=False,
    )

    assert out["domain_name"] == "Student Enrollment"
    assert [row["policy_key"] for row in out["policies"]] == ["workspace_domain_rule", "global_rule"]
    assert out["policies"][0]["is_inherited"] is False
    assert out["policies"][1]["is_inherited"] is True


def test_upsert_policy_rejects_invalid_scope_workspace_mismatch() -> None:
    svc = PlannerRerankPolicyService(sql=_FakeSQL(rows_by_call=[]))
    with pytest.raises(ForgeError) as exc_info:
        svc.upsert_policy(
            workspace_id="ws-1",
            actor_user_id="user-1",
            payload={
                "policy_key": "school_literal_rule",
                "name": "School Literal Rule",
                "scope_type": "workspace",
                "scope_workspace_id": "ws-2",
                "policy_json": {
                    "version": 1,
                    "when_signals_all": ["student_listing"],
                    "prefer_capabilities": ["STUDENT_IDENTITY"],
                    "boost": 0.2,
                    "penalty": 0.0,
                    "max_effect": 0.2,
                },
            },
        )
    assert exc_info.value.status_code == 400


def test_upsert_policy_validates_domain_scope_access() -> None:
    svc = PlannerRerankPolicyService(sql=_FakeSQL(rows_by_call=[[]]))
    with pytest.raises(ForgeError) as exc_info:
        svc.upsert_policy(
            workspace_id="ws-1",
            actor_user_id="user-1",
            payload={
                "policy_key": "school_literal_rule",
                "name": "School Literal Rule",
                "scope_type": "workspace_domain",
                "scope_base_domain_id": 99,
                "policy_json": {
                    "version": 1,
                    "when_signals_all": ["student_listing"],
                    "prefer_capabilities": ["STUDENT_IDENTITY"],
                    "boost": 0.2,
                    "penalty": 0.0,
                    "max_effect": 0.2,
                },
            },
    )
    assert exc_info.value.status_code == 404


def test_upsert_policy_inserts_new_row() -> None:
    sql = _FakeSQL(
        rows_by_call=[
            [_domain_row(domain_id=9)],
            [],
        ],
        insert_results=[ForgeExecResult(rowcount=1, lastrowid=14)],
    )
    svc = PlannerRerankPolicyService(sql=sql)
    out = svc.upsert_policy(
        workspace_id="ws-1",
        actor_user_id="user-1",
        payload={
            "policy_key": "student_listing_school_literal",
            "name": "Student listing school literal",
            "scope_type": "workspace_domain",
            "scope_base_domain_id": 9,
            "policy_json": {
                "version": 1,
                "when_signals_all": ["student_listing", "school_literal_present"],
                "prefer_capabilities": ["STUDENT_IDENTITY", "SCHOOL_NAME"],
                "penalize_missing": ["SCHOOL_NAME"],
                "boost": 0.2,
                "penalty": 0.3,
                "max_effect": 0.3,
            },
        },
    )

    assert out["policy_id"] == 14
    assert sql.write_calls


def test_delete_policy_removes_existing_row() -> None:
    sql = _FakeSQL(
        rows_by_call=[
            [_policy_row(id=14, policy_key="student_listing_school_literal", scope_type="workspace_domain")],
            [_domain_row(domain_id=9)],
        ]
    )
    svc = PlannerRerankPolicyService(sql=sql)
    out = svc.delete_policy(
        workspace_id="ws-1",
        actor_user_id="user-1",
        policy_id=14,
    )

    assert out == {"deleted": True, "policy_id": 14}


def test_get_applicable_policies_returns_empty_on_expected_lookup_error() -> None:
    sql = _FakeSQL(rows_by_call=[])
    sql.execute_query_mappings = lambda query, params=None: (_ for _ in ()).throw(RuntimeError("db unavailable"))  # type: ignore[method-assign]
    svc = PlannerRerankPolicyService(sql=sql)

    out = svc.get_applicable_policies(workspace_id="ws-1", vertical_norm="education", base_domain_id=9)

    assert out == []


def test_get_applicable_policies_surfaces_unexpected_lookup_error() -> None:
    sql = _FakeSQL(rows_by_call=[])
    sql.execute_query_mappings = lambda query, params=None: (_ for _ in ()).throw(AssertionError("lookup bug"))  # type: ignore[method-assign]
    svc = PlannerRerankPolicyService(sql=sql)

    with pytest.raises(AssertionError, match="lookup bug"):
        svc.get_applicable_policies(workspace_id="ws-1", vertical_norm="education", base_domain_id=9)


def test_parse_policy_rule_wraps_expected_json_parse_errors() -> None:
    with pytest.raises(ForgeError, match="Invalid planner rerank policy JSON"):
        planner_rerank_policy_service._parse_policy_rule("{not json}")


def test_parse_policy_rule_surfaces_unexpected_json_parse_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        planner_rerank_policy_service.json,
        "loads",
        lambda value: (_ for _ in ()).throw(AssertionError("json bug")),
    )

    with pytest.raises(AssertionError, match="json bug"):
        planner_rerank_policy_service._parse_policy_rule('{"version": 1}')


def test_parse_policy_rule_wraps_expected_validation_errors() -> None:
    with pytest.raises(ForgeError, match="Invalid planner rerank policy JSON"):
        planner_rerank_policy_service._parse_policy_rule({"version": 1})


def test_parse_policy_rule_surfaces_unexpected_validation_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        planner_rerank_policy_service.PlannerRerankPolicyRule,
        "model_validate",
        lambda value: (_ for _ in ()).throw(AssertionError("validation bug")),
    )

    with pytest.raises(AssertionError, match="validation bug"):
        planner_rerank_policy_service._parse_policy_rule(
            {
                "version": 1,
                "when_signals_all": ["student_listing"],
                "prefer_capabilities": ["STUDENT_IDENTITY"],
                "boost": 0.2,
                "penalty": 0.0,
                "max_effect": 0.2,
            }
        )
