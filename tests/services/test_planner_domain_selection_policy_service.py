from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import pytest
from sqlalchemy.exc import SQLAlchemyError

from app.adapters.query_port import ForgeExecResult
from app.models.domain.planner_domain_selection_policy import PlannerDomainSelectionPolicyUpsertRequest
import app.services.domain.planner_domain_selection_policy_service as selection_policy_service
from app.services.domain.planner_domain_selection_policy_service import PlannerDomainSelectionPolicyService


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


def _policy_row(*, id: int, policy_key: str, scope_type: str, priority: int = 100, score_delta: float = 0.33) -> Dict[str, Any]:
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
                "when_signals_all": ["staff_work_context_prompt"],
                "required_shortlist_features": ["STAFF_IDENTITY_COLUMN"],
                "score_delta": score_delta,
            }
        ),
    }


def test_score_adjustment_for_staff_work_context_shortlist() -> None:
    svc = PlannerDomainSelectionPolicyService(enable_db_lookup=False)

    adjustment = svc.score_adjustment(
        workspace_id="ws-1",
        prompt_signals=["staff_work_context_prompt"],
        shortlist_features=["STAFF_IDENTITY_COLUMN"],
        capability_features=[],
    )

    assert adjustment == 0.14


def test_score_adjustment_for_adm_shortlist_and_metric() -> None:
    svc = PlannerDomainSelectionPolicyService(enable_db_lookup=False)

    adjustment = svc.score_adjustment(
        workspace_id="ws-1",
        prompt_signals=["adm_prompt"],
        shortlist_features=["ADM_SIGNAL_COLUMN"],
        capability_features=["ADM_METRIC"],
    )

    assert adjustment == 0.32


def test_score_adjustment_for_calendar_days_off_combines_shortlist_features() -> None:
    svc = PlannerDomainSelectionPolicyService(enable_db_lookup=False)

    adjustment = svc.score_adjustment(
        workspace_id="ws-1",
        prompt_signals=["calendar_days_off_prompt"],
        shortlist_features=["CALENDAR_DAY_COLUMN", "SCHOOL_DAY_FLAG_COLUMN"],
        capability_features=[],
    )

    assert adjustment == 0.34


def test_domain_selection_policy_service_prefers_workspace_rule_over_global_rule_when_db_lookup_enabled() -> None:
    sql = _FakeSQL(
        rows_by_call=[
            [
                _policy_row(id=7, policy_key="staff_work_identity_selection_boost", scope_type="global", priority=20, score_delta=0.21),
                _policy_row(id=8, policy_key="staff_work_identity_selection_boost", scope_type="workspace", priority=10, score_delta=0.33),
            ]
        ]
    )
    svc = PlannerDomainSelectionPolicyService(sql=sql, enable_db_lookup=True)

    adjustment = svc.score_adjustment(
        workspace_id="ws-1",
        prompt_signals=["staff_work_context_prompt"],
        shortlist_features=["STAFF_IDENTITY_COLUMN"],
        capability_features=[],
    )

    assert adjustment == 0.33


def test_domain_selection_policy_upsert_request_rejects_vertical_scope() -> None:
    with pytest.raises(Exception, match="Invalid scope_type"):
        PlannerDomainSelectionPolicyUpsertRequest.model_validate(
            {
                "policy_key": "custom_domain_selection",
                "name": "Custom domain selection",
                "scope_type": "vertical",
                "scope_vertical_norm": "education",
                "policy_json": {
                    "version": 1,
                    "when_signals_all": ["staff_work_context_prompt"],
                    "required_shortlist_features": ["STAFF_IDENTITY_COLUMN"],
                    "score_delta": 0.2,
                },
            }
        )


def test_domain_selection_policy_upsert_request_rejects_workspace_scope_with_vertical_norm() -> None:
    with pytest.raises(Exception, match="scope_vertical_norm"):
        PlannerDomainSelectionPolicyUpsertRequest.model_validate(
            {
                "policy_key": "custom_domain_selection",
                "name": "Custom domain selection",
                "scope_type": "workspace",
                "scope_vertical_norm": "education",
                "policy_json": {
                    "version": 1,
                    "when_signals_all": ["staff_work_context_prompt"],
                    "required_shortlist_features": ["STAFF_IDENTITY_COLUMN"],
                    "score_delta": 0.2,
                },
            }
        )


def test_domain_selection_policy_service_lists_workspace_specific_policies() -> None:
    sql = _FakeSQL(
        rows_by_call=[
            [
                _policy_row(id=7, policy_key="staff_work_identity_selection_boost", scope_type="workspace", priority=20, score_delta=0.21),
            ]
        ]
    )
    svc = PlannerDomainSelectionPolicyService(sql=sql, enable_db_lookup=True)

    out = svc.list_policies(workspace_id="ws-1", include_inactive=False, include_seeded=True)

    assert out["policies"][0]["scope_type"] == "workspace"
    assert out["policies"][0]["is_effective"] is True


def test_domain_selection_policy_service_upserts_workspace_policy() -> None:
    sql = _FakeSQL(
        rows_by_call=[
            [],
            [
                _policy_row(id=31, policy_key="custom_domain_selection", scope_type="workspace", priority=90),
            ],
        ],
        insert_results=[ForgeExecResult(rowcount=1, lastrowid=31)],
    )
    svc = PlannerDomainSelectionPolicyService(sql=sql, enable_db_lookup=True)

    out = svc.upsert_policy(
        workspace_id="ws-1",
        payload={
            "policy_key": "custom_domain_selection",
            "name": "Custom domain selection",
            "scope_type": "workspace",
            "priority": 90,
            "policy_json": {
                "version": 1,
                "when_signals_all": ["staff_work_context_prompt"],
                "required_shortlist_features": ["STAFF_IDENTITY_COLUMN"],
                "score_delta": 0.33,
            },
        },
    )

    assert out["id"] == 31
    assert out["scope_type"] == "workspace"
    assert "scope_vertical_norm" not in sql.write_calls[0]["params"]


def test_domain_selection_policy_service_delete_policy_removes_existing_row() -> None:
    sql = _FakeSQL(
        rows_by_call=[
            [_policy_row(id=31, policy_key="custom_domain_selection", scope_type="workspace")],
        ]
    )
    svc = PlannerDomainSelectionPolicyService(sql=sql, enable_db_lookup=True)

    out = svc.delete_policy(workspace_id="ws-1", policy_id=31)

    assert out == {"deleted": True, "policy_id": 31, "policy_key": "custom_domain_selection"}


def test_domain_selection_policy_service_falls_back_on_expected_db_lookup_errors() -> None:
    class _RaisingSQL:
        def execute_query_mappings(self, sql, params):
            del sql, params
            raise SQLAlchemyError("db unavailable")

    svc = PlannerDomainSelectionPolicyService(sql=_RaisingSQL(), enable_db_lookup=True)

    adjustment = svc.score_adjustment(
        workspace_id="ws-1",
        prompt_signals=["staff_work_context_prompt"],
        shortlist_features=["STAFF_IDENTITY_COLUMN"],
        capability_features=[],
    )

    assert adjustment == 0.14


def test_domain_selection_policy_service_surfaces_unexpected_policy_parse_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FakeSQLNoop:
        def execute_query_mappings(self, sql, params):
            del sql, params
            return []

    def _boom(_value):
        raise AssertionError("unexpected policy parse bug")

    svc = PlannerDomainSelectionPolicyService(sql=_FakeSQLNoop(), enable_db_lookup=True)
    monkeypatch.setattr(selection_policy_service, "_parse_policy_rule", _boom)

    with pytest.raises(AssertionError, match="unexpected policy parse bug"):
        svc.get_applicable_policies(workspace_id="ws-1")
