from __future__ import annotations

import pytest
from sqlalchemy.exc import SQLAlchemyError

import app.services.domain.planner_retrieval_policy_service as retrieval_policy_service
from app.models.domain.planner_retrieval_policy import PlannerRetrievalPolicyUpsertRequest
from app.services.domain.planner_retrieval_policy_service import PlannerRetrievalPolicyService


def test_build_query_specs_for_age_extreme_prompt() -> None:
    svc = PlannerRetrievalPolicyService(enable_db_lookup=False)

    specs = svc.build_query_specs(
        workspace_id="ws-1",
        prompt_signals=["student_listing", "age_extreme_prompt"],
        semantic_concept_keys=[],
    )

    queries = {str(item["query"]) for item in specs}
    assert "student demographics birth date age" in queries
    assert "student profile date of birth" in queries


def test_build_query_specs_for_staff_work_context_prompt() -> None:
    svc = PlannerRetrievalPolicyService(enable_db_lookup=False)

    specs = svc.build_query_specs(
        workspace_id="ws-1",
        prompt_signals=["staff_work_context_prompt"],
        semantic_concept_keys=[],
    )

    assert any(str(item.get("query") or "").lower() == "staff assignments" for item in specs)


def test_build_query_specs_for_workflow_run_count_prompt() -> None:
    svc = PlannerRetrievalPolicyService(enable_db_lookup=False)

    specs = svc.build_query_specs(
        workspace_id="ws-1",
        prompt_signals=["workflow_intelligence_prompt", "workflow_run_count_prompt"],
        semantic_concept_keys=[],
    )

    assert any("FlowForge Workflow Runs run count" in str(item.get("query") or "") for item in specs)
    assert any("workflow_run_count" in list(item.get("reasons") or []) for item in specs)


def test_build_query_specs_for_adm_prompt() -> None:
    svc = PlannerRetrievalPolicyService(enable_db_lookup=False)

    specs = svc.build_query_specs(
        workspace_id="ws-1",
        prompt_signals=["adm_prompt"],
        semantic_concept_keys=[],
    )

    assert any("average daily membership" in str(item.get("query") or "").lower() for item in specs)


def test_build_query_specs_for_semantic_school_year_pattern() -> None:
    svc = PlannerRetrievalPolicyService(enable_db_lookup=False)

    specs = svc.build_query_specs(
        workspace_id="ws-1",
        prompt_signals=[],
        semantic_concept_keys=["CURRENT_SCHOOL_YEAR"],
    )

    assert any(
        str(item.get("query")) == "school year academic calendar enrollment"
        and float(item.get("score_boost") or 0.0) == 0.04
        for item in specs
    )


def test_score_domain_name_bias_for_calendar_days_off_prompt() -> None:
    svc = PlannerRetrievalPolicyService(enable_db_lookup=False)

    bias = svc.score_domain_name_bias(
        workspace_id="ws-1",
        prompt_signals=["calendar_days_off_prompt"],
        candidate_name="Academic Calendar And Scheduling",
    )

    assert bias == 0.18


def test_score_domain_name_bias_for_staff_work_context_prompt() -> None:
    svc = PlannerRetrievalPolicyService(enable_db_lookup=False)

    staff_bias = svc.score_domain_name_bias(
        workspace_id="ws-1",
        prompt_signals=["staff_work_context_prompt"],
        candidate_name="Staff & Assignments",
    )
    discipline_bias = svc.score_domain_name_bias(
        workspace_id="ws-1",
        prompt_signals=["staff_work_context_prompt"],
        candidate_name="Discipline",
    )

    assert staff_bias > discipline_bias


def test_score_domain_name_bias_prefers_workflow_runs_over_intake_for_run_count_prompt() -> None:
    svc = PlannerRetrievalPolicyService(enable_db_lookup=False)

    runs_bias = svc.score_domain_name_bias(
        workspace_id="ws-1",
        prompt_signals=["workflow_intelligence_prompt", "workflow_run_count_prompt"],
        candidate_name="FlowForge Workflow Runs",
    )
    intake_bias = svc.score_domain_name_bias(
        workspace_id="ws-1",
        prompt_signals=["workflow_intelligence_prompt", "workflow_run_count_prompt"],
        candidate_name="FlowForge Intake Events",
    )

    assert runs_bias > intake_bias
    assert runs_bias > 0
    assert intake_bias < runs_bias


def test_retrieval_policy_service_prefers_workspace_rule_when_db_lookup_enabled() -> None:
    class _FakeSQL:
        def execute_query_mappings(self, sql, params):
            del sql
            assert params["workspace_id"] == "ws-1"
            return [
                {
                    "id": 3,
                    "policy_key": "staff_context_domain_retrieval",
                    "name": "Custom staff context",
                    "description": None,
                    "scope_type": "workspace",
                    "scope_workspace_id": "ws-1",
                    "scope_vertical_norm": "education",
                    "priority": 10,
                    "is_active": 1,
                    "stop_on_match": 0,
                    "policy_json": {
                        "version": 1,
                        "when_signals_any": ["staff_work_context_prompt"],
                        "query_specs": [{"query": "provider territory assignments", "source": "vector"}],
                    },
                }
            ]

    svc = PlannerRetrievalPolicyService(sql=_FakeSQL(), enable_db_lookup=True)

    specs = svc.build_query_specs(
        workspace_id="ws-1",
        prompt_signals=["staff_work_context_prompt"],
        semantic_concept_keys=[],
    )

    queries = {str(item["query"]) for item in specs}
    assert "provider territory assignments" in queries
    assert "staff assignments" not in queries


def test_retrieval_policy_upsert_request_rejects_legacy_scope_types() -> None:
    with pytest.raises(Exception, match="Invalid scope_type"):
        PlannerRetrievalPolicyUpsertRequest.model_validate(
            {
                "policy_key": "custom_retrieval",
                "name": "Custom retrieval",
                "scope_type": "vertical",
                "policy_json": {
                    "version": 1,
                    "when_signals_any": ["staff_work_context_prompt"],
                    "query_specs": [{"query": "foo", "source": "vector"}],
                },
            }
        )


def test_retrieval_policy_service_falls_back_on_expected_db_lookup_errors() -> None:
    class _FakeSQL:
        def execute_query_mappings(self, sql, params):
            del sql, params
            raise SQLAlchemyError("db unavailable")

    svc = PlannerRetrievalPolicyService(sql=_FakeSQL(), enable_db_lookup=True)

    specs = svc.build_query_specs(
        workspace_id="ws-1",
        prompt_signals=["staff_work_context_prompt"],
        semantic_concept_keys=[],
    )

    assert any(str(item.get("query") or "").lower() == "staff assignments" for item in specs)


def test_retrieval_policy_service_surfaces_unexpected_policy_parse_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FakeSQL:
        def execute_query_mappings(self, sql, params):
            del sql, params
            return []

    def _boom(_value):
        raise AssertionError("unexpected policy parse bug")

    svc = PlannerRetrievalPolicyService(sql=_FakeSQL(), enable_db_lookup=True)
    monkeypatch.setattr(retrieval_policy_service, "_parse_policy_rule", _boom)

    with pytest.raises(AssertionError, match="unexpected policy parse bug"):
        svc.get_applicable_policies(workspace_id="ws-1")
