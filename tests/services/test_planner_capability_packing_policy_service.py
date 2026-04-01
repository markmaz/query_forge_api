from app.services.domain.planner_capability_packing_policy_service import PlannerCapabilityPackingPolicyService


def test_packing_policy_returns_school_listing_location_actions() -> None:
    service = PlannerCapabilityPackingPolicyService()

    out = service.get_packing_requirements(
        workspace_id="ws_demo",
        vertical_norm="k12",
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
        vertical_norm="k12",
        prompt_signals=["nativity_prompt"],
        capability_features=[],
    )

    assert "nativity_filter_support" in out["matched_policies"]
    assert out["required_filter_column_names"] == ["birth_country", "country_of_birth", "date_entered_us"]


def test_packing_policy_returns_canonical_name_preference() -> None:
    service = PlannerCapabilityPackingPolicyService()

    out = service.get_packing_requirements(
        workspace_id="ws_demo",
        vertical_norm="k12",
        prompt_signals=["canonical_name_preference_prompt"],
        capability_features=["HAS_CANONICAL_NAME_COLUMNS"],
    )

    assert "canonical_name_preference" in out["matched_policies"]
    assert out["prefer_canonical_name_columns"] is True


def test_packing_policy_returns_name_constraint_support() -> None:
    service = PlannerCapabilityPackingPolicyService()

    out = service.get_packing_requirements(
        workspace_id="ws_demo",
        vertical_norm="k12",
        prompt_signals=["name_constraint_prompt"],
        capability_features=[],
    )

    assert "name_constraint_support" in out["matched_policies"]
    assert out["include_name_constraint_columns"] is True
