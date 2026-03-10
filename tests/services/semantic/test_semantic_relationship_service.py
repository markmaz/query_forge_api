from __future__ import annotations

import pytest

from app.exceptions.forge_error import ForgeError
from app.ports.sql_executor import ForgeExecResult
from app.services.semantic.semantic_relationship_service import SemanticRelationshipService
from tests._support.fakes import FakeForgeQueryPort


def test_relationship_create_success_with_same_vertical() -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses = [
        [
            {"id": 1, "vertical_norm": "education"},
            {"id": 2, "vertical_norm": "education"},
        ],
        [],
        [
            {
                "id": 9,
                "parent_concept_id": 1,
                "child_concept_id": 2,
                "relationship_type": "parent_of",
                "created_at": "2026-01-01",
                "vertical": "education",
                "vertical_norm": "education",
                "parent_concept_key": "student",
                "child_concept_key": "student_id",
            }
        ],
    ]
    sql.insert_responses = [ForgeExecResult(rowcount=1, lastrowid=9)]

    svc = SemanticRelationshipService(sql=sql)
    row = svc.create_relationship(
        {
            "parent_concept_id": 1,
            "child_concept_id": 2,
            "relationship_type": "parent_of",
        }
    )

    assert row["id"] == 9
    assert row["relationship_type"] == "parent_of"


def test_relationship_rejects_cross_vertical() -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses = [
        [
            {"id": 1, "vertical_norm": "education"},
            {"id": 2, "vertical_norm": "healthcare"},
        ]
    ]

    svc = SemanticRelationshipService(sql=sql)
    with pytest.raises(ForgeError, match="Cross-vertical relationships"):
        svc.create_relationship(
            {
                "parent_concept_id": 1,
                "child_concept_id": 2,
                "relationship_type": "parent_of",
            }
        )


def test_relationship_rejects_self_reference() -> None:
    svc = SemanticRelationshipService(sql=FakeForgeQueryPort())

    with pytest.raises(ForgeError, match="must differ"):
        svc.create_relationship(
            {
                "parent_concept_id": 3,
                "child_concept_id": 3,
                "relationship_type": "parent_of",
            }
        )


def test_relationship_rejects_cycle() -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses = [
        [
            {"id": 3, "vertical_norm": "education"},
            {"id": 1, "vertical_norm": "education"},
        ],
        [{"child_concept_id": 2}],
        [{"child_concept_id": 3}],
    ]

    svc = SemanticRelationshipService(sql=sql)

    with pytest.raises(ForgeError, match="cycle"):
        svc.create_relationship(
            {
                "parent_concept_id": 3,
                "child_concept_id": 1,
                "relationship_type": "parent_of",
            }
        )
