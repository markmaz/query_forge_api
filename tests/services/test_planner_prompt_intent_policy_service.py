from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import pytest

from app.adapters.query_port import ForgeExecResult
from app.models.domain.planner_prompt_intent_policy import PlannerPromptIntentPolicyUpsertRequest
from app.services.domain.planner_prompt_intent_policy_service import PlannerPromptIntentPolicyService


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


def _policy_row(*, id: int, policy_key: str, scope_type: str, priority: int = 100, regex_patterns: Optional[list[str]] = None):
    return {
        "id": id,
        "policy_key": policy_key,
        "name": policy_key.replace("_", " ").title(),
        "description": None,
        "scope_type": scope_type,
        "scope_workspace_id": "ws-1" if scope_type == "workspace" else None,
        "scope_vertical_norm": "education" if scope_type == "vertical" else None,
        "priority": priority,
        "is_active": 1,
        "stop_on_match": 0,
        "policy_json": json.dumps(
            {
                "version": 1,
                "action_key": "list_students",
                "regex_patterns": regex_patterns or [r"\bprovider\s+roster\b"],
            }
        ),
    }


def test_looks_like_list_students_respects_aggregate_exclusion() -> None:
    svc = PlannerPromptIntentPolicyService(enable_db_lookup=False)

    assert svc.looks_like_list_students("Show me all the students") is True
    assert svc.looks_like_list_students("How many students are enrolled") is False


def test_prompt_context_policies_split_staff_and_student_context() -> None:
    svc = PlannerPromptIntentPolicyService(enable_db_lookup=False)

    assert svc.prompt_implies_staff_work_context("Show me the teacher at Lincoln High") is True
    assert svc.prompt_implies_student_school_context("Show me the student at Lincoln High") is True
    assert svc.prompt_implies_staff_work_context("Show me the student at Lincoln High") is False


def test_extract_subgroup_terms_dedupes_matches() -> None:
    svc = PlannerPromptIntentPolicyService(enable_db_lookup=False)

    out = svc.extract_subgroup_terms("Show me black students and Black students and hispanic students")

    assert out == ["black", "hispanic"]


def test_extract_time_phrases_uses_seeded_phrase_order() -> None:
    svc = PlannerPromptIntentPolicyService(enable_db_lookup=False)

    assert svc.extract_time_phrases("Show me students enrolled this year") == ["this year"]
    assert svc.extract_time_phrases("Show me students for the school year") == ["school year"]


def test_city_state_pattern_uses_seeded_state_codes() -> None:
    svc = PlannerPromptIntentPolicyService(enable_db_lookup=False)

    assert svc.prompt_has_city_state_pattern("Show me all the schools in Clarksville, TN") is True
    assert svc.prompt_has_city_state_pattern("Show me all the schools in Clarksville, ZZ") is False


def test_prompt_intent_service_prefers_workspace_rule_when_db_lookup_enabled() -> None:
    sql = _FakeSQL(
        rows_by_call=[
            [
                _policy_row(id=7, policy_key="custom_list_students", scope_type="global", priority=20, regex_patterns=[r"\bprovider\s+roster\b"]),
                _policy_row(id=9, policy_key="custom_list_students", scope_type="workspace", priority=10, regex_patterns=[r"\bworkspace\s+roster\b"]),
            ],
            [
                _policy_row(id=7, policy_key="custom_list_students", scope_type="global", priority=20, regex_patterns=[r"\bprovider\s+roster\b"]),
                _policy_row(id=9, policy_key="custom_list_students", scope_type="workspace", priority=10, regex_patterns=[r"\bworkspace\s+roster\b"]),
            ],
            [
                _policy_row(id=7, policy_key="custom_list_students", scope_type="global", priority=20, regex_patterns=[r"\bprovider\s+roster\b"]),
                _policy_row(id=9, policy_key="custom_list_students", scope_type="workspace", priority=10, regex_patterns=[r"\bworkspace\s+roster\b"]),
            ],
        ]
    )
    svc = PlannerPromptIntentPolicyService(sql=sql, enable_db_lookup=True)

    assert svc.looks_like_list_students("workspace roster", workspace_id="ws-1", vertical_norm="education") is True
    assert svc.looks_like_list_students("provider roster", workspace_id="ws-1", vertical_norm="education") is False


def test_prompt_intent_policy_upsert_request_rejects_vertical_scope() -> None:
    with pytest.raises(Exception, match="Invalid scope_type"):
        PlannerPromptIntentPolicyUpsertRequest.model_validate(
            {
                "policy_key": "custom_prompt_intent",
                "name": "Custom prompt intent",
                "scope_type": "vertical",
                "scope_vertical_norm": "education",
                "priority": 100,
                "is_active": True,
                "stop_on_match": False,
                "policy_json": {
                    "version": 1,
                    "action_key": "list_students",
                    "regex_patterns": [r"foo"],
                },
            }
        )


def test_prompt_intent_policy_upsert_request_rejects_workspace_scope_with_vertical_norm() -> None:
    with pytest.raises(Exception, match="scope_vertical_norm"):
        PlannerPromptIntentPolicyUpsertRequest.model_validate(
            {
                "policy_key": "custom_prompt_intent",
                "name": "Custom prompt intent",
                "scope_type": "workspace",
                "scope_vertical_norm": "education",
                "priority": 100,
                "is_active": True,
                "stop_on_match": False,
                "policy_json": {
                    "version": 1,
                    "action_key": "list_students",
                    "regex_patterns": [r"foo"],
                },
            }
        )


def test_prompt_intent_policy_service_lists_workspace_specific_policies() -> None:
    sql = _FakeSQL(
        rows_by_call=[
            [
                _policy_row(id=9, policy_key="custom_list_students", scope_type="workspace", priority=10),
            ]
        ]
    )
    svc = PlannerPromptIntentPolicyService(sql=sql, enable_db_lookup=True)

    out = svc.list_policies(workspace_id="ws-1", vertical_norm="education", include_inactive=False, include_seeded=True)

    assert out["vertical_norm"] == "education"
    assert out["policies"][0]["scope_type"] == "workspace"
    assert out["policies"][0]["is_effective"] is True


def test_prompt_intent_policy_service_upserts_workspace_policy() -> None:
    sql = _FakeSQL(
        rows_by_call=[
            [],
            [
                _policy_row(id=13, policy_key="custom_list_students", scope_type="workspace", priority=100),
            ],
        ],
        insert_results=[ForgeExecResult(rowcount=1, lastrowid=13)],
    )
    svc = PlannerPromptIntentPolicyService(sql=sql, enable_db_lookup=True)

    out = svc.upsert_policy(
        workspace_id="ws-1",
        payload={
            "policy_key": "custom_list_students",
            "name": "Custom list students",
            "scope_type": "workspace",
            "priority": 100,
            "is_active": True,
            "stop_on_match": False,
            "policy_json": {
                "version": 1,
                "action_key": "list_students",
                "regex_patterns": [r"foo"],
            },
        },
    )

    assert out["id"] == 13
    assert out["scope_type"] == "workspace"
    assert "scope_vertical_norm" not in sql.write_calls[0]["params"]


def test_prompt_intent_policy_service_delete_policy_removes_existing_row() -> None:
    sql = _FakeSQL(
        rows_by_call=[
            [_policy_row(id=13, policy_key="custom_list_students", scope_type="workspace")],
        ]
    )
    svc = PlannerPromptIntentPolicyService(sql=sql, enable_db_lookup=True)

    out = svc.delete_policy(workspace_id="ws-1", policy_id=13)

    assert out == {"deleted": True, "policy_id": 13, "policy_key": "custom_list_students"}
