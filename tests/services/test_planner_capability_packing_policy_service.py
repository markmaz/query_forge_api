from __future__ import annotations

import pytest
from sqlalchemy.exc import SQLAlchemyError

import app.services.domain.planner_capability_packing_policy_service as capability_packing_policy_service
from app.services.domain.planner_capability_packing_policy_service import PlannerCapabilityPackingPolicyService


def test_packing_policy_returns_school_listing_location_actions() -> None:
    service = PlannerCapabilityPackingPolicyService()

    out = service.get_packing_requirements(
        workspace_id="ws_demo",
        prompt_signals=["school_listing", "city_state_prompt"],
        capability_features=["HAS_PREFERRED_STATE_COLUMN"],
    )

    assert "school_listing_location_append" in out["matched_policies"]
    assert "school_listing_city_state_cleanup" in out["matched_policies"]
    assert "city" in out["append_column_names"]
    assert "state_code" in out["append_first_match_column_names"]
    assert ["state_code", "state"] in out["append_first_match_column_name_groups"]
    assert "state_school_code" in out["excluded_column_names"]


def test_packing_policy_returns_nativity_filter_support() -> None:
    service = PlannerCapabilityPackingPolicyService()

    out = service.get_packing_requirements(
        workspace_id="ws_demo",
        prompt_signals=["nativity_prompt"],
        capability_features=[],
    )

    assert "nativity_filter_support" in out["matched_policies"]
    assert out["required_filter_column_names"] == ["birth_country", "country_of_birth", "date_entered_us"]


def test_packing_policy_returns_canonical_name_preference() -> None:
    service = PlannerCapabilityPackingPolicyService()

    out = service.get_packing_requirements(
        workspace_id="ws_demo",
        prompt_signals=["canonical_name_preference_prompt"],
        capability_features=["HAS_CANONICAL_NAME_COLUMNS"],
    )

    assert "canonical_name_preference" in out["matched_policies"]
    assert out["prefer_canonical_name_columns"] is True


def test_packing_policy_returns_name_constraint_support() -> None:
    service = PlannerCapabilityPackingPolicyService()

    out = service.get_packing_requirements(
        workspace_id="ws_demo",
        prompt_signals=["name_constraint_prompt"],
        capability_features=[],
    )

    assert "name_constraint_support" in out["matched_policies"]
    assert out["include_name_constraint_columns"] is True


def test_packing_policy_service_falls_back_on_expected_db_lookup_errors() -> None:
    class _FakeSQL:
        def execute_query_mappings(self, sql, params):
            del sql, params
            raise SQLAlchemyError("db unavailable")

    service = PlannerCapabilityPackingPolicyService(sql=_FakeSQL(), enable_db_lookup=True)

    out = service.get_packing_requirements(
        workspace_id="ws_demo",
        prompt_signals=["school_listing", "city_state_prompt"],
        capability_features=["HAS_PREFERRED_STATE_COLUMN"],
    )

    assert "school_listing_location_append" in out["matched_policies"]


def test_packing_policy_service_surfaces_unexpected_policy_parse_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FakeSQL:
        def execute_query_mappings(self, sql, params):
            del sql, params
            return []

    def _boom(_value):
        raise AssertionError("unexpected policy parse bug")

    service = PlannerCapabilityPackingPolicyService(sql=_FakeSQL(), enable_db_lookup=True)
    monkeypatch.setattr(capability_packing_policy_service, "_parse_policy_rule", _boom)

    with pytest.raises(AssertionError, match="unexpected policy parse bug"):
        service.get_packing_requirements(
            workspace_id="ws_demo",
            prompt_signals=["school_listing"],
            capability_features=[],
        )
