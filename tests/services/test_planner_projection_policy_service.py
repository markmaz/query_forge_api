from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import pytest

from app.adapters.query_port import ForgeExecResult
from app.exceptions.forge_error import ForgeError
from app.services.domain.planner_projection_policy_service import PlannerProjectionPolicyService


class _FakeSQL:
    def __init__(self, *, rows_by_call: List[List[Dict[str, Any]]]) -> None:
        self._rows_by_call = list(rows_by_call)
        self._call_index = 0
        self.write_calls: list[tuple[str, Dict[str, Any]]] = []
        self.insert_calls: list[tuple[str, Dict[str, Any]]] = []
        self.query_calls: list[tuple[str, Dict[str, Any]]] = []

    def execute_query_mappings(self, query: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        self.query_calls.append((query, dict(params or {})))
        if self._call_index >= len(self._rows_by_call):
            return []
        rows = self._rows_by_call[self._call_index]
        self._call_index += 1
        return [dict(row) for row in rows]

    def execute_write(self, query: str, params: Optional[Dict[str, Any]] = None) -> int:
        self.write_calls.append((query, dict(params or {})))
        return 1

    def transaction(self):
        return _FakeTx(self)


class _FakeTx:
    def __init__(self, sql: _FakeSQL) -> None:
        self._sql = sql

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        del exc_type, exc, tb
        return False

    def execute_write(self, query: str, params: Optional[Dict[str, Any]] = None) -> int:
        self._sql.write_calls.append((query, dict(params or {})))
        return 1

    def execute_insert(self, query: str, params: Optional[Dict[str, Any]] = None) -> ForgeExecResult:
        self._sql.insert_calls.append((query, dict(params or {})))
        return ForgeExecResult(rowcount=1, lastrowid=44)


def _policy_row(*, id: int, policy_key: str, scope_type: str, priority: int = 100, required_concepts: Optional[list[str]] = None):
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
                "projection_mode": "prepend",
                "required_concept_keys": required_concepts or ["STUDENT_ID", "STUDENT_FIRST_NAME", "STUDENT_LAST_NAME"],
            }
        ),
    }


def test_projection_policy_service_returns_seeded_student_listing_defaults() -> None:
    svc = PlannerProjectionPolicyService(sql=_FakeSQL(rows_by_call=[[]]))
    out = svc.get_projection_requirements(
        workspace_id="ws-1",
        base_domain_id=9,
        prompt_signals=["student_listing", "needs_student_identity"],
    )

    assert out["projection_mode"] == "prepend"
    assert out["required_concept_keys"] == ["STUDENT_ID", "STUDENT_FIRST_NAME", "STUDENT_LAST_NAME"]
    assert out["excluded_concept_keys"] == []
    assert out["matched_policies"] == ["student_listing_identity_projection"]


def test_projection_policy_service_returns_seeded_human_school_filter_defaults() -> None:
    svc = PlannerProjectionPolicyService(sql=_FakeSQL(rows_by_call=[[]]))
    out = svc.get_projection_requirements(
        workspace_id="ws-1",
        base_domain_id=9,
        prompt_signals=["needs_school_filter", "school_literal_present"],
    )

    assert out["required_concept_keys"] == ["SCHOOL_NAME"]
    assert out["excluded_concept_keys"] == ["SCHOOL_ID"]
    assert "human_school_filter_projection" in out["matched_policies"]


def test_projection_policy_service_returns_seeded_staff_role_filter_defaults() -> None:
    svc = PlannerProjectionPolicyService(sql=_FakeSQL(rows_by_call=[[]]))
    out = svc.get_projection_requirements(
        workspace_id="ws-1",
        base_domain_id=9,
        prompt_signals=["staff_role_prompt"],
    )

    assert out["required_concept_keys"] == ["STAFF_ROLE"]
    assert out["excluded_concept_keys"] == ["STAFF_CLASSIFICATION"]
    assert "human_staff_role_filter_projection" in out["matched_policies"]


def test_projection_policy_service_returns_seeded_school_listing_defaults() -> None:
    svc = PlannerProjectionPolicyService(sql=_FakeSQL(rows_by_call=[[]]))
    out = svc.get_projection_requirements(
        workspace_id="ws-1",
        base_domain_id=9,
        prompt_signals=["school_listing", "listing_intent"],
    )

    assert out["required_column_names"] == ["school_name", "lea_name", "school_number"]
    assert "school_listing_projection" in out["matched_policies"]


def test_projection_policy_service_prefers_more_specific_db_policy_over_seed() -> None:
    svc = PlannerProjectionPolicyService(
        sql=_FakeSQL(
            rows_by_call=[
                [
                    _policy_row(
                        id=7,
                        policy_key="student_listing_identity_projection",
                        scope_type="workspace",
                        priority=20,
                        required_concepts=["STUDENT_ID", "STUDENT_FIRST_NAME"],
                    )
                ]
            ]
        )
    )
    out = svc.get_projection_requirements(
        workspace_id="ws-1",
        base_domain_id=9,
        prompt_signals=["student_listing"],
    )

    assert out["required_concept_keys"] == ["STUDENT_ID", "STUDENT_FIRST_NAME"]
    assert out["excluded_concept_keys"] == []
    assert out["matched_policies"] == ["student_listing_identity_projection"]


def test_projection_policy_service_prefers_domain_and_workspace_scope_over_less_specific_rules() -> None:
    svc = PlannerProjectionPolicyService(
        sql=_FakeSQL(
            rows_by_call=[
                [
                    _policy_row(id=1, policy_key="student_listing_identity_projection", scope_type="global", priority=200),
                    _policy_row(id=2, policy_key="student_listing_identity_projection", scope_type="workspace", priority=150, required_concepts=["STUDENT_ID"]),
                    _policy_row(
                        id=3,
                        policy_key="student_listing_identity_projection",
                        scope_type="workspace_domain",
                        priority=120,
                        required_concepts=["STUDENT_ID", "STUDENT_FIRST_NAME"],
                    ),
                ]
            ]
        )
    )

    out = svc.get_projection_requirements(
        workspace_id="ws-1",
        base_domain_id=9,
        prompt_signals=["student_listing"],
    )

    assert out["required_concept_keys"] == ["STUDENT_ID", "STUDENT_FIRST_NAME"]
    assert out["matched_policies"] == ["student_listing_identity_projection"]


def test_projection_policy_service_lists_seeded_and_db_policies() -> None:
    svc = PlannerProjectionPolicyService(
        sql=_FakeSQL(
            rows_by_call=[
                [
                    {
                        "id": 21,
                        "policy_key": "student_listing_identity_projection",
                        "name": "Workspace student listing identity projection",
                        "description": "Workspace override",
                        "scope_type": "workspace",
                        "scope_workspace_id": "ws-1",
                        "scope_vertical_norm": None,
                        "scope_base_domain_id": None,
                        "priority": 50,
                        "is_active": 1,
                        "stop_on_match": 0,
                        "policy_json": json.dumps(
                            {
                                "version": 1,
                                "when_signals_all": ["student_listing"],
                                "projection_mode": "prepend",
                                "required_concept_keys": ["STUDENT_ID"],
                            }
                        ),
                        "created_at": "2026-03-31T12:00:00",
                        "updated_at": "2026-03-31T12:00:00",
                    }
                ]
            ]
        )
    )

    out = svc.list_policies(workspace_id="ws-1", base_domain_id=None)

    assert out["workspace_id"] == "ws-1"
    assert out["policies"][0]["id"] == 21
    assert out["policies"][0]["is_seeded"] is False
    assert out["policies"][0]["is_effective"] is True
    assert any(row["is_seeded"] is True for row in out["policies"])


def test_projection_policy_service_upserts_policy() -> None:
    sql = _FakeSQL(
        rows_by_call=[
            [{"domain_id": 9, "domain_name": "Enrollment"}],
            [],
            [
                {
                    "id": 44,
                    "policy_key": "custom_school_listing",
                    "name": "Custom school listing",
                    "description": "Workspace override",
                    "scope_type": "workspace_domain",
                    "scope_workspace_id": "ws-1",
                    "scope_vertical_norm": None,
                    "scope_base_domain_id": 9,
                    "priority": 90,
                    "is_active": 1,
                    "stop_on_match": 0,
                    "policy_json": json.dumps(
                        {
                            "version": 1,
                            "when_signals_all": ["school_listing"],
                            "projection_mode": "prepend",
                            "required_column_names": ["school_name"],
                        }
                    ),
                    "created_at": "2026-03-31T12:00:00",
                    "updated_at": "2026-03-31T12:00:00",
                }
            ],
        ]
    )
    svc = PlannerProjectionPolicyService(sql=sql)

    out = svc.upsert_policy(
        workspace_id="ws-1",
        payload={
            "policy_key": "custom_school_listing",
            "name": "Custom school listing",
            "scope_type": "workspace_domain",
            "scope_base_domain_id": 9,
            "priority": 90,
            "policy_json": {
                "version": 1,
                "when_signals_all": ["school_listing"],
                "projection_mode": "prepend",
                "required_column_names": ["school_name"],
            },
        },
    )

    assert sql.insert_calls
    assert out["id"] == 44
    assert out["policy_key"] == "custom_school_listing"
    assert out["scope_type"] == "workspace_domain"
    assert out["policy_json"]["required_column_names"] == ["school_name"]
    assert "scope_vertical_norm" not in sql.insert_calls[0][1]
    assert sql.insert_calls[0][1]["scope_base_domain_id"] == 9


def test_projection_policy_service_upsert_rejects_missing_domain_scope_row() -> None:
    svc = PlannerProjectionPolicyService(sql=_FakeSQL(rows_by_call=[[]]))

    with pytest.raises(ForgeError, match="Domain not found"):
        svc.upsert_policy(
            workspace_id="ws-1",
            payload={
                "policy_key": "custom_school_listing",
                "name": "Custom school listing",
                "scope_type": "workspace_domain",
                "scope_base_domain_id": 9,
                "policy_json": {
                    "version": 1,
                    "when_signals_all": ["school_listing"],
                    "projection_mode": "prepend",
                    "required_column_names": ["school_name"],
                },
            },
        )


def test_projection_policy_service_interpolates_scope_predicate() -> None:
    sql = _FakeSQL(rows_by_call=[[]])
    svc = PlannerProjectionPolicyService(sql=sql)

    svc.get_applicable_policies(
        workspace_id="ws-1",
        base_domain_id=9,
    )

    query, params = sql.query_calls[0]
    assert "{global_workspace_query_predicate()}" not in query
    assert "scope_type = 'global'" in query
    assert params["workspace_id"] == "ws-1"


class _RaisingSQL(_FakeSQL):
    def execute_query_mappings(self, query: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        self.query_calls.append((query, dict(params or {})))
        raise RuntimeError("planner_projection_policy table missing")


def test_projection_policy_service_keeps_seeded_defaults_when_db_lookup_fails() -> None:
    svc = PlannerProjectionPolicyService(sql=_RaisingSQL(rows_by_call=[]))
    out = svc.get_projection_requirements(
        workspace_id="ws-1",
        base_domain_id=9,
        prompt_signals=["student_listing"],
    )

    assert out["required_concept_keys"] == [
        "STUDENT_ID",
        "STUDENT_FIRST_NAME",
        "STUDENT_LAST_NAME",
    ]
    assert out["matched_policies"] == ["student_listing_identity_projection"]
