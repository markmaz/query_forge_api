from __future__ import annotations

import pytest

from app.models.domain.planner_signal_policy import PlannerSignalPolicyUpsertRequest
from app.services.domain.planner_signal_policy_service import PlannerSignalPolicyService


def test_extract_policy_signals_for_student_enrollment_prompt() -> None:
    svc = PlannerSignalPolicyService(enable_db_lookup=False)

    out = svc.extract_policy_signals(prompt="Show me all the students enrolled at Barksdale Elementary")

    assert "student_listing" in out
    assert "status_enrolled" in out
    assert "school_literal_present" in out


def test_extract_policy_signals_for_days_off_prompt() -> None:
    svc = PlannerSignalPolicyService(enable_db_lookup=False)

    out = svc.extract_policy_signals(prompt="How many days off are there in December?")

    assert "calendar_days_off_prompt" in out
    assert "time_constraint_present" in out


def test_extract_policy_signals_for_staff_classification_prompt() -> None:
    svc = PlannerSignalPolicyService(enable_db_lookup=False)

    out = svc.extract_policy_signals(prompt="Show me the staff classification at Lincoln High")

    assert "explicit_staff_classification_request" in out
    assert "school_literal_present" in out
    assert "staff_work_context_prompt" in out


def test_extract_policy_signals_prefers_workspace_rule_when_db_lookup_enabled() -> None:
    class _FakeSQL:
        def execute_query_mappings(self, sql, params):
            del sql
            assert params["workspace_id"] == "ws-1"
            return [
                {
                    "id": 7,
                    "policy_key": "custom_listing_signal",
                    "name": "Custom listing signal",
                    "description": None,
                    "scope_type": "workspace",
                    "scope_workspace_id": "ws-1",
                    "scope_vertical_norm": "education",
                    "priority": 10,
                    "is_active": 1,
                    "stop_on_match": 0,
                    "policy_json": {
                        "version": 1,
                        "signal_keys": ["listing_intent"],
                        "match_type": "regex",
                        "patterns": [r"\bprovider\s+roster\b"],
                    },
                }
            ]

    svc = PlannerSignalPolicyService(sql=_FakeSQL(), enable_db_lookup=True)

    out = svc.extract_policy_signals(prompt="provider roster", workspace_id="ws-1")

    assert out == ["listing_intent"]


def test_signal_policy_upsert_request_rejects_legacy_scope_types() -> None:
    with pytest.raises(Exception, match="Invalid scope_type"):
        PlannerSignalPolicyUpsertRequest.model_validate(
            {
                "policy_key": "custom_signal",
                "name": "Custom signal",
                "scope_type": "vertical",
                "priority": 100,
                "is_active": True,
                "stop_on_match": False,
                "policy_json": {
                    "version": 1,
                    "signal_keys": ["listing_intent"],
                    "match_type": "regex",
                    "patterns": [r"foo"],
                },
            }
        )
