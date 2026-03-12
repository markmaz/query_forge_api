from __future__ import annotations

from datetime import datetime

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
                "parent_concept_name": "Student",
                "child_concept_name": "Student Id",
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
        [{"child_concept_id": 2, "relationship_type": "depends_on"}],
        [{"child_concept_id": 3, "relationship_type": "depends_on"}],
    ]

    svc = SemanticRelationshipService(sql=sql)

    with pytest.raises(ForgeError, match="cycle"):
        svc.create_relationship(
            {
                "parent_concept_id": 3,
                "child_concept_id": 1,
                "relationship_type": "depends_on",
            }
        )


def test_get_relationship_not_found() -> None:
    svc = SemanticRelationshipService(sql=FakeForgeQueryPort())
    with pytest.raises(ForgeError, match="not found"):
        svc.get_relationship(99)


def test_patch_relationship_updates_type() -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses = [
        [
            {
                "id": 10,
                "parent_concept_id": 1,
                "child_concept_id": 2,
                "relationship_type": "belongs_to_domain",
                "created_at": "2026-01-01",
                "vertical": "generic",
                "vertical_norm": "generic",
                "parent_concept_key": "DOMAIN_SALES",
                "child_concept_key": "TOTAL_NET_AMOUNT",
                "parent_concept_name": "Sales Performance",
                "child_concept_name": "Total Net Amount",
            }
        ],
        [
            {"id": 1, "vertical_norm": "generic"},
            {"id": 2, "vertical_norm": "generic"},
        ],
        [
            {
                "id": 10,
                "parent_concept_id": 1,
                "child_concept_id": 2,
                "relationship_type": "default_time_field_for",
                "created_at": "2026-01-01",
                "vertical": "generic",
                "vertical_norm": "generic",
                "parent_concept_key": "TOTAL_NET_AMOUNT",
                "child_concept_key": "ORDER_DATE",
                "parent_concept_name": "Total Net Amount",
                "child_concept_name": "Order Date",
            }
        ],
    ]
    sql.write_responses = [1]

    svc = SemanticRelationshipService(sql=sql)
    row = svc.patch_relationship(10, {"relationship_type": "default_time_field_for"})
    assert row["id"] == 10
    assert row["relationship_type"] == "default_time_field_for"


def test_patch_relationship_rejects_cycle_on_edge_change() -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses = [
        [
            {
                "id": 10,
                "parent_concept_id": 1,
                "child_concept_id": 2,
                "relationship_type": "depends_on",
                "created_at": "2026-01-01",
                "vertical": "generic",
                "vertical_norm": "generic",
                "parent_concept_key": "A",
                "child_concept_key": "B",
            }
        ],
        [
            {"id": 3, "vertical_norm": "generic"},
            {"id": 1, "vertical_norm": "generic"},
        ],
        [{"child_concept_id": 2, "relationship_type": "depends_on"}],
        [{"child_concept_id": 3, "relationship_type": "depends_on"}],
    ]

    svc = SemanticRelationshipService(sql=sql)
    with pytest.raises(ForgeError, match="cycle"):
        svc.patch_relationship(
            10,
            {
                "parent_concept_id": 3,
                "child_concept_id": 1,
            },
        )


def test_relationship_cycle_check_skipped_for_default_time_field_for() -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses = [
        [
            {"id": 65, "vertical_norm": "generic"},
            {"id": 56, "vertical_norm": "generic"},
        ],
        [
            {
                "id": 178,
                "parent_concept_id": 65,
                "child_concept_id": 56,
                "relationship_type": "default_time_field_for",
                "created_at": "2026-03-11",
                "vertical": "generic",
                "vertical_norm": "generic",
                "parent_concept_key": "TOTAL_GROSS_AMOUNT",
                "child_concept_key": "ORDER_DATE",
                "parent_concept_name": "Total Gross Amount",
                "child_concept_name": "Order Date",
            }
        ],
    ]
    sql.insert_responses = [ForgeExecResult(rowcount=1, lastrowid=178)]

    svc = SemanticRelationshipService(sql=sql)
    out = svc.create_relationship(
        {
            "parent_concept_id": 65,
            "child_concept_id": 56,
            "relationship_type": "default_time_field_for",
        }
    )
    assert out["id"] == 178


def test_delete_relationship_not_found() -> None:
    sql = FakeForgeQueryPort()
    sql.write_responses = [0]
    svc = SemanticRelationshipService(sql=sql)
    with pytest.raises(ForgeError, match="not found"):
        svc.delete_relationship(777)


def test_list_concept_lookup_human_readable() -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses = [
        [
            {
                "id": 1,
                "vertical_norm": "generic",
                "concept_key": "TOTAL_NET_AMOUNT",
                "semantic_type": "metric",
                "description": "Total net sales amount",
                "concept_name": "Total Net Amount",
            }
        ],
        [{"total": 1}],
    ]
    svc = SemanticRelationshipService(sql=sql)
    out = svc.list_concept_lookup(vertical="generic", q="sales", page=1, page_size=100)
    assert out["total"] == 1
    assert out["rows"][0]["concept_name"] == "Total Net Amount"
    assert out["rows"][0]["display_label"] == "Total Net Amount (TOTAL_NET_AMOUNT)"


def test_get_relationship_serializes_datetime_fields() -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses = [
        [
            {
                "id": 77,
                "parent_concept_id": 1,
                "child_concept_id": 2,
                "relationship_type": "default_time_field_for",
                "created_at": datetime(2026, 3, 11, 20, 23, 20),
                "vertical": "generic",
                "vertical_norm": "generic",
                "parent_concept_key": "TOTAL_NET_AMOUNT",
                "parent_concept_name": "Total Net Amount",
                "child_concept_key": "ORDER_DATE",
                "child_concept_name": "Order Date",
            }
        ]
    ]
    svc = SemanticRelationshipService(sql=sql)
    row = svc.get_relationship(77)
    assert row["created_at"] == "2026-03-11T20:23:20"
