from __future__ import annotations

from datetime import datetime
from typing import Optional

import pytest

from app.services.semantic.semantic_concept_service import SemanticConceptService
from app.exceptions.forge_error import ForgeError
from app.ports.sql_executor import ForgeExecResult
from tests._support.fakes import FakeForgeQueryPort


class _GatewayStub:
    def __init__(self) -> None:
        self.calls: list[Optional[str]] = []


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
    assert sql.query_mappings_calls[0].params == {}


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

    result = svc.list_concept_keys()

    assert result == {"concept_keys": ["ATTENDANCE_RATE", "SCHOOL_YEAR"]}
    assert len(sql.query_mappings_calls) == 1
    query = sql.query_mappings_calls[0].query
    assert "SELECT DISTINCT concept_key" in query
    assert "ORDER BY concept_key ASC" in query
    assert sql.query_mappings_calls[0].params == {}


def test_list_concepts_reads_without_vertical_filter() -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses = [[], [{"total": 0}]]
    svc = SemanticConceptService(sql=sql)

    result = svc.list_concepts(page=1, page_size=25)

    assert result["total"] == 0
    assert len(sql.query_mappings_calls) == 2
    assert sql.query_mappings_calls[0].params == {"limit": 25, "offset": 0}
    assert sql.query_mappings_calls[1].params == {}


def test_seed_uses_generic_compatibility_set() -> None:
    sql = FakeForgeQueryPort()
    svc = SemanticConceptService(sql=sql)

    svc.seed()

    concept_calls = [call for call in sql.write_calls if "INSERT INTO semantic_concept" in call.query]
    alias_calls = [call for call in sql.write_calls if "INSERT INTO semantic_concept_alias" in call.query]
    concept_keys = {str((call.params or {}).get("concept_key") or "") for call in concept_calls}
    alias_keys = {str((call.params or {}).get("alias_key") or "") for call in alias_calls}

    assert "STUDENT_ID" in concept_keys
    assert "SCHOOL_YEAR" in concept_keys
    assert "DATE" in concept_keys
    assert "k_school" in alias_keys
    assert all("vertical_norm" not in (call.params or {}) for call in concept_calls)
    assert all("vertical_norm" not in (call.params or {}) for call in alias_calls)


def test_seed_no_longer_returns_vertical_norm() -> None:
    sql = FakeForgeQueryPort()
    svc = SemanticConceptService(sql=sql)

    result = svc.seed()

    assert "vertical_norm" not in result


def test_list_concept_keys_reads_without_vertical_filter() -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses = [[]]
    svc = SemanticConceptService(sql=sql)

    result = svc.list_concept_keys()

    assert result == {"concept_keys": []}
    assert sql.query_mappings_calls[0].params == {}


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
    assert "LOWER(wc.column_name) LIKE :column_name" in list_query
    assert "LOWER(sc.name) LIKE :q" in list_query
    assert "JOIN semantic_concept sc ON sc.id = m.semantic_concept_id" in count_query
    assert "JOIN workspace_column wc" in count_query
    assert "JOIN workspace_table wt" in count_query
    assert list_params["concept_key"] == "%district%"
    assert list_params["column_name"] == "%name%"
    assert list_params["q"] == "%district%"
    assert count_params["concept_key"] == "%district%"
    assert count_params["column_name"] == "%name%"
    assert count_params["q"] == "%district%"


def test_backfill_primary_semantic_keys_dry_run() -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses = [[{"total": 3}]]
    svc = SemanticConceptService(sql=sql)

    result = svc.backfill_primary_semantic_keys(
        workspace_id="ws-1",
        dry_run=True,
    )

    assert result["dry_run"] is True
    assert result["candidates"] == 3
    assert result["updated"] == 0
    assert len(sql.query_mappings_calls) == 1
    query = sql.query_mappings_calls[0].query
    params = sql.query_mappings_calls[0].params or {}
    assert "m.relationship_kind = 'primary'" in query
    assert "wc.semantic_concept_key IS NULL" in query
    assert "JOIN workspace_table wt" in query
    assert params["workspace_id"] == "ws-1"


def test_backfill_primary_semantic_keys_execute() -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses = [[{"total": 2}]]
    sql.write_responses = [2]
    svc = SemanticConceptService(sql=sql)

    result = svc.backfill_primary_semantic_keys(
        workspace_id=None,
        dry_run=False,
    )

    assert result["dry_run"] is False
    assert result["candidates"] == 2
    assert result["updated"] == 2
    assert len(sql.write_calls) >= 1
    update_query = next(call.query for call in sql.write_calls if "UPDATE workspace_column wc" in call.query)
    assert "UPDATE workspace_column wc" in update_query
    assert "SET wc.semantic_concept_id = r.semantic_concept_id" in update_query
    assert "wc.semantic_concept_key = r.concept_key" in update_query


def test_backfill_primary_semantic_keys_execute_updates_workspace_columns() -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses = [[{"total": 1}]]
    sql.write_responses = [1]
    gateway = _GatewayStub()
    svc = SemanticConceptService(sql=sql, metadata_gateway=gateway)  # type: ignore[arg-type]

    result = svc.backfill_primary_semantic_keys(
        workspace_id="ws-42",
        dry_run=False,
    )

    assert result["updated"] == 1
    assert gateway.calls == []


def test_create_concept_column_map_accepts_workspace_column_id() -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses = [
        [{"id": 10}],
        [{"id": 88}],
        [
            {
                "id": 7,
                "vertical_norm": "education",
                "semantic_concept_id": 10,
                "concept_key": "DISTRICT_NAME",
                "concept_name": "District Name",
                "model_column_id": 20,
                "workspace_column_id": 88,
                "column_name": "lea_name",
                "model_table_name": "dim_school",
                "relationship_kind": "primary",
                "weight": 1.0,
                "created_at": datetime(2026, 2, 17, 12, 0, 0),
            }
        ],
    ]
    sql.insert_responses = [ForgeExecResult(rowcount=1, lastrowid=7)]
    svc = SemanticConceptService(sql=sql)

    row = svc.create_concept_column_map(
        {
            "vertical_norm": "education",
            "semantic_concept_id": 10,
            "workspace_column_id": 88,
        }
    )
    assert row["id"] == 7
    assert row["model_column_id"] == 20
    assert row["workspace_column_id"] == 88


def test_create_alias_rejects_non_numeric_weight() -> None:
    svc = SemanticConceptService(sql=FakeForgeQueryPort())

    with pytest.raises(ForgeError, match="weight must be numeric"):
        svc.create_alias(
            {
                "vertical_norm": "education",
                "alias_key": "k_school",
                "concept_key": "SCHOOL_ID",
                "weight": "not-a-number",
            }
        )


def test_create_alias_surfaces_unexpected_weight_conversion_errors() -> None:
    class _BadFloat:
        def __float__(self) -> float:
            raise RuntimeError("bad weight conversion")

    svc = SemanticConceptService(sql=FakeForgeQueryPort())

    with pytest.raises(RuntimeError, match="bad weight conversion"):
        svc.create_alias(
            {
                "vertical_norm": "education",
                "alias_key": "k_school",
                "concept_key": "SCHOOL_ID",
                "weight": _BadFloat(),
            }
        )
