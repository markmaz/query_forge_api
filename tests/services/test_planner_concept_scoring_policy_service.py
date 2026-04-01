from app.services.domain.planner_concept_scoring_policy_service import PlannerConceptScoringPolicyService


def test_concept_scoring_policy_resolves_entity_match_multiplier() -> None:
    service = PlannerConceptScoringPolicyService()

    out = service.resolve_factor(
        action_key="entity_exact_match_multiplier",
        context_tokens=["entity_exact_match"],
        default=1.0,
    )

    assert out == 1.4


def test_concept_scoring_policy_resolves_subgroup_identifier_penalty() -> None:
    service = PlannerConceptScoringPolicyService()

    out = service.resolve_penalty(
        action_key="identifier_penalty_subgroup",
        context_tokens=["identifier_rebalance", "subgroup_intent"],
        default=0.2,
    )

    assert out == 0.35


def test_concept_scoring_policy_resolves_student_cross_entity_name_penalty() -> None:
    service = PlannerConceptScoringPolicyService()

    out = service.resolve_factor(
        action_key="student_cross_entity_name_multiplier",
        context_tokens=["intent_student", "staff_name_concept"],
        default=1.0,
    )

    assert out == 0.5
