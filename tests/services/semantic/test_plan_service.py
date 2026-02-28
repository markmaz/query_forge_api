from __future__ import annotations

from app.services.semantic.plan_service import PlanService


def test_normalize_llm_payload_coerces_common_alternate_shapes() -> None:
    candidate_columns = [
        {"model_column_id": 383, "concept_key": "RACE", "table_name": "dim_student", "column_name": "race_array"},
        {"model_column_id": 381, "concept_key": "IS_HOMELESS", "table_name": "dim_student", "column_name": "is_homeless"},
        {"model_column_id": 286, "concept_key": "DISTRICT_NAME", "table_name": "dim_school", "column_name": "congressional_district"},
        {"model_column_id": 1080, "concept_key": "GRADE_LEVEL", "table_name": "fct_student_school_association", "column_name": "entry_grade_level"},
    ]
    payload = {
        "sql_json": {"select": {"value": ["dim_student.race_array"]}},
        "selected_columns": [383, 381],
        "filters": [
            {"model_column_id": 1080, "operator": "=", "value": "3"},
            {"model_column_id": 383, "operator": "=", "value": "black"},
        ],
        "join_plan": [{"left_table": "a", "right_table": "b"}],
        "confidence": 0.85,
        "notes": "single note",
    }

    out = PlanService._normalize_llm_payload(payload, candidate_columns=candidate_columns)

    assert out["selected_columns"] == [
        {"concept_key": "RACE", "model_column_id": 383},
        {"concept_key": "IS_HOMELESS", "model_column_id": 381},
    ]
    assert out["filters"] == [
        {"concept_key": "GRADE_LEVEL", "op": "=", "value": "3"},
        {"concept_key": "RACE", "op": "=", "value": "black"},
    ]
    assert out["join_plan"] == {"joins": [{"left_table": "a", "right_table": "b"}]}
    assert out["notes"] == ["single note"]
    assert out["confidence"] == 0.85


def test_normalize_llm_payload_can_map_filter_column_expression() -> None:
    candidate_columns = [
        {"model_column_id": 383, "concept_key": "RACE", "table_name": "dim_student", "column_name": "race_array"},
    ]
    payload = {
        "sql_json": {"where": {"conditions": []}},
        "selected_columns": [],
        "filters": [{"column": "dim_student.race_array", "operator": "=", "value": "black"}],
        "join_plan": {},
        "notes": [],
        "confidence": 2.2,
    }

    out = PlanService._normalize_llm_payload(payload, candidate_columns=candidate_columns)
    assert out["filters"] == [{"concept_key": "RACE", "op": "=", "value": "black"}]
    assert out["confidence"] == 1.0
