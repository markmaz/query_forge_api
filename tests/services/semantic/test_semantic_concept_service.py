from __future__ import annotations

from datetime import datetime

from app.services.semantic.semantic_concept_service import SemanticConceptService
from tests._support.fakes import FakeForgeQueryPort


def test_list_aliases_serializes_created_at_datetime() -> None:
    sql = FakeForgeQueryPort()
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
    sql = FakeForgeQueryPort()
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
    sql = FakeForgeQueryPort()
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


def test_list_value_aliases_includes_concept_name() -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses = [
        [
            {
                "id": 7,
                "vertical_norm": "education",
                "semantic_concept_id": 10,
                "concept_key": "DISTRICT_NAME",
                "concept_name": "District Name",
                "canonical_value": "Acme USD",
                "alias_value": "acme",
                "match_kind": "contains",
                "weight": 1.0,
                "created_at": datetime(2026, 2, 17, 10, 5, 0),
            }
        ],
        [{"total": 1}],
    ]
    svc = SemanticConceptService(sql=sql)

    result = svc.list_value_aliases(page=1, page_size=25)

    row = result["rows"][0]
    assert row["semantic_concept_id"] == 10
    assert row["concept_key"] == "DISTRICT_NAME"
    assert row["concept_name"] == "District Name"
    assert row["created_at"] == "2026-02-17T10:05:00"


def test_list_concept_keys_returns_distinct_sorted_keys() -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses = [
        [
            {"concept_key": "ATTENDANCE_RATE"},
            {"concept_key": "SCHOOL_YEAR"},
        ]
    ]
    svc = SemanticConceptService(sql=sql)

    result = svc.list_concept_keys(vertical="Education")

    assert result == {"concept_keys": ["ATTENDANCE_RATE", "SCHOOL_YEAR"]}
    assert len(sql.query_mappings_calls) == 1
    query = sql.query_mappings_calls[0].query
    assert "SELECT DISTINCT concept_key" in query
    assert "ORDER BY concept_key ASC" in query
    assert sql.query_mappings_calls[0].params == {"vertical_norm": "education"}


def test_list_concept_column_maps_supports_typeahead_filters() -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses = [
        [
            {
                "id": 5,
                "vertical_norm": "education",
                "semantic_concept_id": 10,
                "concept_key": "DISTRICT_NAME",
                "concept_name": "District Name",
                "model_column_id": 20,
                "column_name": "district_name",
                "model_table_name": "dim_district",
                "relationship_kind": "primary",
                "weight": 1.0,
                "created_at": datetime(2026, 2, 17, 12, 0, 0),
            }
        ],
        [{"total": 1}],
    ]
    svc = SemanticConceptService(sql=sql)

    result = svc.list_concept_column_maps(
        vertical="Education",
        concept_key="district",
        column_name="name",
        q="district",
        page=1,
        page_size=25,
    )

    assert result["total"] == 1
    assert result["rows"][0]["concept_key"] == "DISTRICT_NAME"
    assert len(sql.query_mappings_calls) == 2
    list_query = sql.query_mappings_calls[0].query
    count_query = sql.query_mappings_calls[1].query
    list_params = sql.query_mappings_calls[0].params
    count_params = sql.query_mappings_calls[1].params
    assert "LOWER(sc.concept_key) LIKE :concept_key" in list_query
    assert "LOWER(mc.column_name) LIKE :column_name" in list_query
    assert "LOWER(sc.name) LIKE :q" in list_query
    assert "JOIN semantic_concept sc ON sc.id = m.semantic_concept_id" in count_query
    assert "JOIN model_column mc ON mc.id = m.model_column_id" in count_query
    assert "LEFT JOIN model_table mt ON mt.id = mc.model_table_id" in count_query
    assert list_params["vertical_norm"] == "education"
    assert list_params["concept_key"] == "%district%"
    assert list_params["column_name"] == "%name%"
    assert list_params["q"] == "%district%"
    assert count_params["vertical_norm"] == "education"
    assert count_params["concept_key"] == "%district%"
    assert count_params["column_name"] == "%name%"
    assert count_params["q"] == "%district%"


def test_backfill_primary_semantic_keys_dry_run() -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses = [[{"total": 3}]]
    svc = SemanticConceptService(sql=sql)

    result = svc.backfill_primary_semantic_keys(
        workspace_id="ws-1",
        vertical_norm="education",
        dry_run=True,
    )

    assert result["dry_run"] is True
    assert result["candidates"] == 3
    assert result["updated"] == 0
    assert len(sql.query_mappings_calls) == 1
    query = sql.query_mappings_calls[0].query
    params = sql.query_mappings_calls[0].params or {}
    assert "m.relationship_kind = 'primary'" in query
    assert "mc.semantic_concept_key IS NULL" in query
    assert "JOIN workspace_table wt" in query
    assert params["workspace_id"] == "ws-1"
    assert params["vertical_norm"] == "education"


def test_backfill_primary_semantic_keys_execute() -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses = [[{"total": 2}]]
    sql.write_responses = [2]
    svc = SemanticConceptService(sql=sql)

    result = svc.backfill_primary_semantic_keys(
        workspace_id=None,
        vertical_norm=None,
        dry_run=False,
    )

    assert result["dry_run"] is False
    assert result["candidates"] == 2
    assert result["updated"] == 2
    assert len(sql.write_calls) == 1
    update_query = sql.write_calls[0].query
    assert "UPDATE model_column mc" in update_query
    assert "SET mc.semantic_concept_id = r.semantic_concept_id" in update_query
    assert "mc.semantic_concept_key = r.concept_key" in update_query
