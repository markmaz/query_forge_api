from __future__ import annotations

import pytest

from app.models.domain.planner_prompt_intent_policy import PlannerPromptIntentPolicyUpsertRequest
from app.services.domain.planner_prompt_intent_policy_service import PlannerPromptIntentPolicyService


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
    class _FakeSQL:
        def execute_query_mappings(self, sql, params):
            del sql
            assert params["workspace_id"] == "ws-1"
            return [
                {
                    "id": 9,
                    "policy_key": "custom_list_students",
                    "name": "Custom list students",
                    "description": None,
                    "scope_type": "workspace",
                    "scope_workspace_id": "ws-1",
                    "scope_vertical_norm": "education",
                    "priority": 10,
                    "is_active": 1,
                    "stop_on_match": 0,
                    "policy_json": {
                        "version": 1,
                        "action_key": "list_students",
                        "regex_patterns": [r"\bprovider\s+roster\b"],
                    },
                }
            ]

    svc = PlannerPromptIntentPolicyService(sql=_FakeSQL(), enable_db_lookup=True)

    assert svc.looks_like_list_students("provider roster", workspace_id="ws-1") is True


def test_prompt_intent_policy_upsert_request_rejects_legacy_scope_types() -> None:
    with pytest.raises(Exception, match="Invalid scope_type"):
        PlannerPromptIntentPolicyUpsertRequest.model_validate(
            {
                "policy_key": "custom_prompt_intent",
                "name": "Custom prompt intent",
                "scope_type": "vertical",
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
