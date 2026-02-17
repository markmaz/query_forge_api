from __future__ import annotations

from datetime import datetime

from app.services.semantic.semantic_concept_service import SemanticConceptService
from tests._support.fakes import FakeSQLExecutor


def test_list_aliases_serializes_created_at_datetime() -> None:
    sql = FakeSQLExecutor()
    sql.query_mappings_responses = [
        [
            {
                "id": 1,
                "vertical_norm": "education",
                "alias_key": "k_school",
                "concept_key": "SCHOOL_ID",
                "match_kind": "exact",
                "weight": 1.0,
                "created_at": datetime(2026, 2, 16, 17, 23, 40),
            }
        ]
    ]
    svc = SemanticConceptService(sql=sql)

    result = svc.list_aliases()
    assert result["rows"][0]["created_at"] == "2026-02-16T17:23:40"


def test_list_concepts_serializes_datetime_fields() -> None:
    sql = FakeSQLExecutor()
    sql.query_mappings_responses = [
        [
            {
                "id": 11,
                "vertical_norm": "education",
                "concept_key": "SCHOOL_YEAR",
                "name": "School Year",
                "description": None,
                "semantic_type": "time",
                "sub_type": "time.year",
                "entity": "student",
                "granularity_rank": 0,
                "filter_allowed": 1,
                "group_by_allowed": 1,
                "aggregation_allowed": 0,
                "is_identifier": 0,
                "is_metric": 0,
                "display_priority": 0,
                "sensitive": 0,
                "status": "active",
                "created_at": datetime(2026, 2, 16, 17, 0, 0),
                "updated_at": datetime(2026, 2, 16, 18, 0, 0),
            }
        ],
        [{"total": 1}],
    ]
    svc = SemanticConceptService(sql=sql)

    result = svc.list_concepts(page=1, page_size=25)
    row = result["rows"][0]
    assert row["created_at"] == "2026-02-16T17:00:00"
    assert row["updated_at"] == "2026-02-16T18:00:00"


def test_list_concept_column_maps_includes_human_readable_names() -> None:
    sql = FakeSQLExecutor()
    sql.query_mappings_responses = [
        [
            {
                "id": 3,
                "vertical_norm": "education",
                "semantic_concept_id": 10,
                "concept_key": "SCHOOL_ID",
                "concept_name": "School ID",
                "model_column_id": 24,
                "column_name": "k_school",
                "model_table_name": "dim_student_enrollment",
                "relationship_kind": "primary",
                "weight": 1.0,
                "created_at": datetime(2026, 2, 16, 19, 0, 0),
            }
        ],
        [{"total": 1}],
    ]
    svc = SemanticConceptService(sql=sql)

    result = svc.list_concept_column_maps(page=1, page_size=25)
    row = result["rows"][0]
    assert row["concept_name"] == "School ID"
    assert row["column_name"] == "k_school"
    assert row["model_table_name"] == "dim_student_enrollment"
    assert row["created_at"] == "2026-02-16T19:00:00"
