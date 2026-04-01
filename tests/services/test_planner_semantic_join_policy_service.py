from app.services.domain.planner_semantic_join_policy_service import PlannerSemanticJoinPolicyService


def test_semantic_join_policy_prefers_dim_school_school_name_for_school_filters() -> None:
    service = PlannerSemanticJoinPolicyService()

    dim_school_rank = service.filter_column_rank(
        concept_key="SCHOOL_NAME",
        row={
            "__selected__": False,
            "table_name": "dim_school",
            "column_name": "school_name",
            "effective_weight": 1.2,
            "model_column_id": 10,
        },
    )
    fact_rank = service.filter_column_rank(
        concept_key="SCHOOL_NAME",
        row={
            "__selected__": False,
            "table_name": "fct_student_school_association",
            "column_name": "school_name",
            "effective_weight": 1.3,
            "model_column_id": 11,
        },
    )

    assert dim_school_rank < fact_rank


def test_semantic_join_policy_adds_student_school_join() -> None:
    service = PlannerSemanticJoinPolicyService()

    out = service.ensure_required_join_plan(
        join_plan={},
        selected_tables=["dim_student"],
        present_filter_concept_keys=["SCHOOL_NAME"],
        required_join_tables=["dim_school"],
    )

    assert out["primary_table"] == "dim_student"
    assert out["joins"] == [
        {
            "table": "dim_school",
            "on": [{"concept_key": "SCHOOL_ID", "op": "=", "value": "SCHOOL_ID"}],
        }
    ]
