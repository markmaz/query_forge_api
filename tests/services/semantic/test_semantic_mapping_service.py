from __future__ import annotations

import pytest

from app.exceptions.forge_error import ForgeError
from app.ports.sql_executor import ForgeExecResult
from app.services.semantic.semantic_mapping_service import SemanticMappingService
from tests._support.fakes import FakeForgeQueryPort


def test_mapping_create_with_model_column_id() -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses = [
        [{"id": 99}],
        [
            {
                "id": 10,
                "semantic_registry_id": 99,
                "workspace_id": "ws1",
                "workspace_norm": "ws1",
                "model_column_id": 123,
                "table_name": None,
                "column_name": None,
                "priority_rank": 2,
                "confidence_score": 0.95,
                "created_at": "2026-01-01",
                "concept_key": "student.first_name",
                "vertical": "education",
                "vertical_norm": "education",
                "semantic_type": "attribute",
                "entity": "student",
            }
        ],
    ]
    sql.insert_responses = [ForgeExecResult(rowcount=1, lastrowid=10)]

    svc = SemanticMappingService(sql=sql)
    row = svc.create_mapping(
        {
            "semantic_registry_id": 99,
            "workspace_id": "ws1",
            "model_column_id": 123,
            "priority_rank": 2,
            "confidence_score": 0.95,
        }
    )

    assert row["id"] == 10
    assert row["model_column_id"] == 123
    assert row["table_name"] is None


def test_mapping_create_with_table_and_column() -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses = [
        [{"id": 42}],
        [
            {
                "id": 11,
                "semantic_registry_id": 42,
                "workspace_id": None,
                "workspace_norm": "__global__",
                "model_column_id": None,
                "table_name": "students",
                "column_name": "first_name",
                "priority_rank": 1,
                "confidence_score": 0.7,
                "created_at": "2026-01-01",
                "concept_key": "student.first_name",
                "vertical": None,
                "vertical_norm": "__global__",
                "semantic_type": "attribute",
                "entity": "student",
            }
        ],
    ]
    sql.insert_responses = [ForgeExecResult(rowcount=1, lastrowid=11)]

    svc = SemanticMappingService(sql=sql)
    row = svc.create_mapping(
        {
            "semantic_registry_id": 42,
            "table_name": "students",
            "column_name": "first_name",
            "priority_rank": 1,
        }
    )

    assert row["id"] == 11
    assert row["table_name"] == "students"
    assert row["column_name"] == "first_name"


def test_mapping_rejects_missing_identifiers() -> None:
    svc = SemanticMappingService(sql=FakeForgeQueryPort())

    with pytest.raises(ForgeError, match=r"mapping requires model_column_id or table_name\+column_name"):
        svc.create_mapping({"semantic_registry_id": 1})


def test_resolve_best_column_for_concept_prefers_priority_then_confidence() -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses = [
        [
            {
                "id": 1,
                "semantic_registry_id": 7,
                "workspace_id": None,
                "workspace_norm": "__global__",
                "model_column_id": 11,
                "table_name": None,
                "column_name": None,
                "priority_rank": 10,
                "confidence_score": 0.2,
                "created_at": "2026-01-01",
                "concept_key": "student.id",
                "vertical": "education",
                "vertical_norm": "education",
                "semantic_type": "identifier",
                "entity": "student",
            },
            {
                "id": 2,
                "semantic_registry_id": 7,
                "workspace_id": "ws1",
                "workspace_norm": "ws1",
                "model_column_id": 12,
                "table_name": None,
                "column_name": None,
                "priority_rank": 3,
                "confidence_score": 0.9,
                "created_at": "2026-01-01",
                "concept_key": "student.id",
                "vertical": "education",
                "vertical_norm": "education",
                "semantic_type": "identifier",
                "entity": "student",
            },
        ]
    ]

    svc = SemanticMappingService(sql=sql)
    row = svc.resolve_best_column_for_concept("student.id", "education", "ws1")

    assert row is not None
    assert row["id"] == 2


def test_find_concepts_for_column_requires_identifier() -> None:
    svc = SemanticMappingService(sql=FakeForgeQueryPort())

    with pytest.raises(ForgeError, match=r"model_column_id or table_name\+column_name is required"):
        svc.find_concepts_for_column(workspace_id="ws1")
