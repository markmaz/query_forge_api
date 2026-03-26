from __future__ import annotations

from typing import Any, Dict, List, Optional

import pytest

from app.adapters.query_port import ForgeExecResult
from app.exceptions.forge_error import ForgeError
from app.services.domain.planner_rerank_policy_candidate_service import PlannerRerankPolicyCandidateService


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


class _FakePolicyService:
    def __init__(self) -> None:
        self.calls: List[Dict[str, Any]] = []

    def upsert_policy(self, *, workspace_id: str, actor_user_id: str, payload: Any) -> Dict[str, Any]:
        self.calls.append(
            {
                "workspace_id": workspace_id,
                "actor_user_id": actor_user_id,
                "payload": dict(payload),
            }
        )
        return {
            "policy_id": 77,
            "policy_key": payload["policy_key"],
            "scope_type": payload["scope_type"],
            "policy_json": dict(payload["policy_json"]),
        }


def test_create_candidate_rejects_invalid_workspace_override() -> None:
    svc = PlannerRerankPolicyCandidateService(sql=_FakeSQL(rows_by_call=[]), policy_service=_FakePolicyService())
    with pytest.raises(ForgeError) as exc_info:
        svc.create_candidate(
            workspace_id="ws-1",
            payload={
                "candidate_key": "candidate_1",
                "workspace_id": "ws-2",
                "candidate_policy": {
                    "version": 1,
                    "when_signals_all": ["student_listing"],
                    "prefer_capabilities": ["STUDENT_IDENTITY"],
                    "boost": 0.2,
                    "max_effect": 0.2,
                },
            },
        )
    assert exc_info.value.status_code == 400


def test_create_candidate_persists_pending_candidate() -> None:
    sql = _FakeSQL(rows_by_call=[], insert_results=[ForgeExecResult(rowcount=1, lastrowid=5)])
    svc = PlannerRerankPolicyCandidateService(sql=sql, policy_service=_FakePolicyService())
    out = svc.create_candidate(
        workspace_id="ws-1",
        payload={
            "candidate_key": "candidate_1",
            "source_type": "ai_recommendation",
            "candidate_policy": {
                "version": 1,
                "when_signals_all": ["student_listing", "school_literal_present"],
                "prefer_capabilities": ["STUDENT_IDENTITY", "SCHOOL_NAME"],
                "penalize_missing": ["SCHOOL_NAME"],
                "boost": 0.2,
                "penalty": 0.3,
                "max_effect": 0.3,
            },
            "rationale_json": {"prompt": "Show students enrolled at Barksdale Elementary"},
            "confidence": 0.82,
        },
    )

    assert out["candidate_id"] == 5
    assert out["review_status"] == "pending"
    assert sql.write_calls


def test_delete_candidate_removes_existing_row() -> None:
    sql = _FakeSQL(
        rows_by_call=[
            [
                {
                    "id": 5,
                    "candidate_key": "candidate_1",
                    "source_type": "ai_recommendation",
                    "workspace_id": "ws-1",
                    "vertical_norm": "education",
                    "candidate_json": {
                        "version": 1,
                        "when_signals_all": ["student_listing"],
                        "prefer_capabilities": ["STUDENT_IDENTITY"],
                        "boost": 0.2,
                        "max_effect": 0.2,
                    },
                    "review_status": "pending",
                    "approved_policy_id": None,
                }
            ]
        ]
    )
    svc = PlannerRerankPolicyCandidateService(sql=sql, policy_service=_FakePolicyService())
    out = svc.delete_candidate(workspace_id="ws-1", candidate_id=5)

    assert out == {"deleted": True, "candidate_id": 5}


def test_approve_candidate_promotes_into_policy() -> None:
    sql = _FakeSQL(
        rows_by_call=[
            [
                {
                    "id": 5,
                    "candidate_key": "candidate_1",
                    "source_type": "ai_recommendation",
                    "workspace_id": "ws-1",
                    "vertical_norm": "education",
                    "candidate_json": {
                        "version": 1,
                        "when_signals_all": ["student_listing", "school_literal_present"],
                        "prefer_capabilities": ["STUDENT_IDENTITY", "SCHOOL_NAME"],
                        "penalize_missing": ["SCHOOL_NAME"],
                        "boost": 0.2,
                        "penalty": 0.3,
                        "max_effect": 0.3,
                    },
                    "review_status": "pending",
                    "approved_policy_id": None,
                }
            ]
        ]
    )
    policies = _FakePolicyService()
    svc = PlannerRerankPolicyCandidateService(sql=sql, policy_service=policies)
    out = svc.approve_candidate(
        workspace_id="ws-1",
        actor_user_id="user-1",
        candidate_id=5,
        payload={
            "name": "Student listing school literal",
            "scope_type": "workspace_domain",
            "scope_base_domain_id": 9,
        },
    )

    assert out["review_status"] == "approved"
    assert out["approved_policy_id"] == 77
    assert policies.calls[0]["payload"]["policy_key"] == "candidate_1"
    assert sql.write_calls


def test_list_candidates_validates_review_status() -> None:
    svc = PlannerRerankPolicyCandidateService(sql=_FakeSQL(rows_by_call=[]), policy_service=_FakePolicyService())
    with pytest.raises(ForgeError) as exc_info:
        svc.list_candidates(workspace_id="ws-1", review_status="bad")
    assert exc_info.value.status_code == 400
