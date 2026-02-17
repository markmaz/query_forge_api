from __future__ import annotations

import pytest

from app.exceptions.service_error import ServiceError
from app.ports.sql_executor import ExecuteResult
from app.services.semantic.semantic_registry_service import SemanticRegistryService
from tests._support.fakes import FakeSQLExecutor


def test_registry_create_success() -> None:
    sql = FakeSQLExecutor()
    sql.insert_responses = [ExecuteResult(rowcount=1, lastrowid=5)]
    sql.query_mappings_responses = [
        [
            {
                "id": 5,
                "vertical": "education",
                "vertical_norm": "education",
                "concept_key": "student.first_name",
                "semantic_type": "attribute",
                "sub_type": None,
                "entity": "student",
                "description": "first name",
                "granularity_rank": 0,
                "filter_allowed": 1,
                "group_by_allowed": 1,
                "aggregation_allowed": 0,
                "is_identifier": 0,
                "is_metric": 0,
                "display_priority": 10,
                "sensitive": 0,
                "created_at": "2026-01-01",
                "updated_at": "2026-01-01",
            }
        ]
    ]

    svc = SemanticRegistryService(sql=sql)
    row = svc.create_entry(
        {
            "vertical": "education",
            "concept_key": "student.first_name",
            "semantic_type": "attribute",
            "entity": "student",
            "aggregation_allowed": False,
            "display_priority": 10,
        }
    )

    assert row["id"] == 5
    assert row["semantic_type"] == "attribute"
    assert row["aggregation_allowed"] is False


def test_registry_invalid_semantic_type_rejected() -> None:
    svc = SemanticRegistryService(sql=FakeSQLExecutor())

    with pytest.raises(ServiceError, match="semantic_type must be one of"):
        svc.create_entry(
            {
                "concept_key": "bad",
                "semantic_type": "not_real",
            }
        )


def test_registry_duplicate_constraint_maps_to_conflict() -> None:
    sql = FakeSQLExecutor()
    sql.insert_exceptions = [Exception("Duplicate entry 'education-student.id' for key 'uq_semantic_registry_vertical_concept'")]
    svc = SemanticRegistryService(sql=sql)

    with pytest.raises(ServiceError) as exc:
        svc.create_entry({"vertical": "education", "concept_key": "student.id", "semantic_type": "identifier"})

    assert exc.value.status_code == 409


def test_registry_list_filtering_uses_expected_predicates() -> None:
    sql = FakeSQLExecutor()
    sql.query_mappings_responses = [
        [
            {
                "id": 2,
                "vertical": "education",
                "vertical_norm": "education",
                "concept_key": "student.id",
                "semantic_type": "identifier",
                "sub_type": None,
                "entity": "student",
                "description": "id",
                "granularity_rank": 0,
                "filter_allowed": 1,
                "group_by_allowed": 1,
                "aggregation_allowed": 1,
                "is_identifier": 1,
                "is_metric": 0,
                "display_priority": 0,
                "sensitive": 0,
                "created_at": "2026-01-01",
                "updated_at": "2026-01-01",
            }
        ],
        [{"total": 1}],
    ]

    svc = SemanticRegistryService(sql=sql)
    result = svc.list_entries(
        vertical="education",
        q="student",
        semantic_type="identifier",
        entity="student",
        page=2,
        page_size=10,
    )

    assert result["total"] == 1
    assert result["page"] == 2
    assert result["page_size"] == 10

    query = sql.query_mappings_calls[0].query
    assert "sr.vertical_norm = :vertical_norm" in query
    assert "sr.semantic_type = :semantic_type" in query
    assert "LOWER(COALESCE(sr.entity, '')) = :entity" in query
    assert "LOWER(sr.concept_key) LIKE :q" in query


def test_registry_update_and_delete() -> None:
    sql = FakeSQLExecutor()
    sql.write_responses = [1, 1]
    sql.query_mappings_responses = [
        [
            {
                "id": 7,
                "vertical": None,
                "vertical_norm": "__global__",
                "concept_key": "global.concept",
                "semantic_type": "other",
                "sub_type": None,
                "entity": None,
                "description": None,
                "granularity_rank": 1,
                "filter_allowed": 1,
                "group_by_allowed": 1,
                "aggregation_allowed": 1,
                "is_identifier": 0,
                "is_metric": 0,
                "display_priority": 0,
                "sensitive": 0,
                "created_at": "2026-01-01",
                "updated_at": "2026-01-01",
            }
        ]
    ]

    svc = SemanticRegistryService(sql=sql)
    updated = svc.update_entry(7, {"granularity_rank": 1})
    assert updated["id"] == 7

    svc.delete_entry(7)
    assert len(sql.write_calls) == 2
