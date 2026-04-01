from app.services.domain.planner_semantic_projection_policy_service import PlannerSemanticProjectionPolicyService


def test_semantic_projection_policy_returns_student_default_projection() -> None:
    service = PlannerSemanticProjectionPolicyService()
    assert service.default_projection_concepts(entity="student") == [
        "STUDENT_ID",
        "STUDENT_FIRST_NAME",
        "FIRST_NAME",
        "STUDENT_LAST_NAME",
        "LAST_NAME",
    ]


def test_semantic_projection_policy_returns_student_name_filter_concepts() -> None:
    service = PlannerSemanticProjectionPolicyService()
    assert service.name_filter_concepts(entity="student") == [
        "STUDENT_LAST_NAME",
        "LAST_NAME",
        "STUDENT_FIRST_NAME",
        "FIRST_NAME",
    ]


def test_semantic_projection_policy_returns_student_name_concept_family() -> None:
    service = PlannerSemanticProjectionPolicyService()
    assert service.concept_family(concept_key="STUDENT_FIRST_NAME") == (
        "STUDENT_FIRST_NAME",
        "FIRST_NAME",
    )
