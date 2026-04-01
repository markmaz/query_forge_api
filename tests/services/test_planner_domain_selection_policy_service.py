from __future__ import annotations

import pytest

from app.models.domain.planner_domain_selection_policy import PlannerDomainSelectionPolicyUpsertRequest
from app.services.domain.planner_domain_selection_policy_service import PlannerDomainSelectionPolicyService


def test_score_adjustment_for_staff_work_context_shortlist() -> None:
    svc = PlannerDomainSelectionPolicyService(enable_db_lookup=False)

    adjustment = svc.score_adjustment(
        workspace_id="ws-1",
        vertical_norm="education",
        prompt_signals=["staff_work_context_prompt"],
        shortlist_features=["STAFF_IDENTITY_COLUMN"],
        capability_features=[],
    )

    assert adjustment == 0.14


def test_score_adjustment_for_adm_shortlist_and_metric() -> None:
    svc = PlannerDomainSelectionPolicyService(enable_db_lookup=False)

    adjustment = svc.score_adjustment(
        workspace_id="ws-1",
        vertical_norm="education",
        prompt_signals=["adm_prompt"],
        shortlist_features=["ADM_SIGNAL_COLUMN"],
        capability_features=["ADM_METRIC"],
    )

    assert adjustment == 0.32


def test_score_adjustment_for_calendar_days_off_combines_shortlist_features() -> None:
    svc = PlannerDomainSelectionPolicyService(enable_db_lookup=False)

    adjustment = svc.score_adjustment(
        workspace_id="ws-1",
        vertical_norm="education",
        prompt_signals=["calendar_days_off_prompt"],
        shortlist_features=["CALENDAR_DAY_COLUMN", "SCHOOL_DAY_FLAG_COLUMN"],
        capability_features=[],
    )

    assert adjustment == 0.34


def test_domain_selection_policy_service_prefers_workspace_rule_when_db_lookup_enabled() -> None:
    class _FakeSQL:
        def execute_query_mappings(self, sql, params):
            del sql
            assert params["workspace_id"] == "ws-1"
            return [
                {
                    "id": 7,
                    "policy_key": "staff_work_identity_selection_boost",
                    "name": "Custom staff identity boost",
                    "description": None,
                    "scope_type": "workspace",
                    "scope_workspace_id": "ws-1",
                    "scope_vertical_norm": "education",
                    "priority": 10,
                    "is_active": 1,
                    "stop_on_match": 0,
                    "policy_json": {
                        "version": 1,
                        "when_signals_all": ["staff_work_context_prompt"],
                        "required_shortlist_features": ["STAFF_IDENTITY_COLUMN"],
                        "score_delta": 0.33,
                    },
                }
            ]

    svc = PlannerDomainSelectionPolicyService(sql=_FakeSQL(), enable_db_lookup=True)

    adjustment = svc.score_adjustment(
        workspace_id="ws-1",
        vertical_norm="education",
        prompt_signals=["staff_work_context_prompt"],
        shortlist_features=["STAFF_IDENTITY_COLUMN"],
        capability_features=[],
    )

    assert adjustment == 0.33


def test_domain_selection_policy_upsert_request_rejects_legacy_scope_types() -> None:
    with pytest.raises(Exception, match="Invalid scope_type"):
        PlannerDomainSelectionPolicyUpsertRequest.model_validate(
            {
                "policy_key": "custom_domain_selection",
                "name": "Custom domain selection",
                "scope_type": "vertical",
                "policy_json": {
                    "version": 1,
                    "when_signals_all": ["staff_work_context_prompt"],
                    "required_shortlist_features": ["STAFF_IDENTITY_COLUMN"],
                    "score_delta": 0.2,
                },
            }
        )
