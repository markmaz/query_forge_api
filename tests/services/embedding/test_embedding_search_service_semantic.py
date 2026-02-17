from __future__ import annotations

from app.services.embedding.embedding_search_service import (
    _apply_hybrid_scoring,
    detect_semantic_intent,
)


def test_detect_semantic_intent_city_listing_and_time() -> None:
    intent = detect_semantic_intent("Show all students by city for school year 2024")
    assert intent["geography_level"] == "city"
    assert intent["wants_aggregation"] is False
    assert intent["wants_listing"] is True
    assert intent["entity_type"] == "student"
    assert intent["time_reference"] == "school_year"
    assert intent["wants_grade_level"] is False


def test_detect_semantic_intent_aggregation() -> None:
    intent = detect_semantic_intent("How many students are in each county?")
    assert intent["wants_aggregation"] is True
    assert intent["geography_level"] == "county"


def test_detect_semantic_intent_grade_level() -> None:
    intent = detect_semantic_intent("show students in 3rd grade level")
    assert intent["wants_grade_level"] is True


def test_apply_hybrid_scoring_city_vs_county_semantic_boost() -> None:
    semantic_intent = detect_semantic_intent("show students by city")
    items = [
        {"kind": "column", "rawScore": 0.6, "columnName": "school_city", "tableName": "students", "semanticType": "geography.city"},
        {"kind": "column", "rawScore": 0.6, "columnName": "name_of_county", "tableName": "students", "semanticType": "geography.county"},
    ]
    scored = _apply_hybrid_scoring(
        items,
        query_text="show students by city",
        workspace_id="ws1",
        domain_id=None,
        workspace_table_ids=None,
        origin=None,
        model_table_id=None,
        source_table_name=None,
        semantic_intent=semantic_intent,
    )
    assert scored[0]["semanticBoost"] > scored[1]["semanticBoost"]
    assert scored[0]["semanticBoost"] == 0.08
    assert scored[1]["semanticBoost"] == -0.05


def test_apply_hybrid_scoring_metric_boost_for_aggregation() -> None:
    semantic_intent = detect_semantic_intent("count students")
    items = [
        {"kind": "column", "rawScore": 0.5, "columnName": "days_attended", "tableName": "students", "semanticType": "metric.days_attended"},
    ]
    scored = _apply_hybrid_scoring(
        items,
        query_text="count students",
        workspace_id=None,
        domain_id=None,
        workspace_table_ids=None,
        origin=None,
        model_table_id=None,
        source_table_name=None,
        semantic_intent=semantic_intent,
    )
    assert scored[0]["semanticBoost"] == 0.05


def test_apply_hybrid_scoring_identifier_boost_for_listing() -> None:
    semantic_intent = detect_semantic_intent("list students")
    items = [
        {"kind": "column", "rawScore": 0.5, "columnName": "student_id", "tableName": "students", "semanticType": "identifier.student_id"},
    ]
    scored = _apply_hybrid_scoring(
        items,
        query_text="list students",
        workspace_id=None,
        domain_id=None,
        workspace_table_ids=None,
        origin=None,
        model_table_id=None,
        source_table_name=None,
        semantic_intent=semantic_intent,
    )
    assert scored[0]["semanticBoost"] == 0.03


def test_apply_hybrid_scoring_grade_level_integer_boost() -> None:
    semantic_intent = detect_semantic_intent("show students in grade level 3")
    items = [
        {
            "kind": "column",
            "rawScore": 0.5,
            "columnName": "grade_level",
            "tableName": "students",
            "dataType": "INT",
            "semanticType": "attribute.student.grade_level",
        },
        {
            "kind": "column",
            "rawScore": 0.5,
            "columnName": "grade_level_text",
            "tableName": "students",
            "dataType": "STRING",
            "semanticType": "attribute.student.grade_level",
        },
    ]
    scored = _apply_hybrid_scoring(
        items,
        query_text="show students in grade level 3",
        workspace_id=None,
        domain_id=None,
        workspace_table_ids=None,
        origin=None,
        model_table_id=None,
        source_table_name=None,
        semantic_intent=semantic_intent,
    )
    assert scored[0]["gradeBoost"] > scored[1]["gradeBoost"]
    assert scored[0]["score"] > scored[1]["score"]
