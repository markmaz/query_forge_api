from __future__ import annotations

from app.services.semantic.semantic_registry_graph_normalization_service import (
    SemanticRegistryGraphNormalizationService,
)
from tests._support.fakes import FakeForgeQueryPort


def test_audit_legacy_registry_graph_rows_counts_registry_maps_and_relationships() -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses = [
        [{"count": 2}],
        [{"count": 5}],
        [{"count": 7}],
    ]
    svc = SemanticRegistryGraphNormalizationService(sql=sql)

    out = svc.audit_legacy_registry_graph_rows()

    assert out == {
        "semantic_registry": 2,
        "semantic_column_map": 5,
        "semantic_relationship": 7,
    }
    assert "FROM semantic_registry sr" in sql.query_mappings_calls[0].query
    assert "FROM semantic_column_map scm" in sql.query_mappings_calls[1].query
    assert "FROM semantic_relationship rel" in sql.query_mappings_calls[2].query


def test_normalize_legacy_registry_graph_dry_run_skips_writes() -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses = [
        [{"count": 1}],
        [{"count": 3}],
        [{"count": 4}],
    ]
    svc = SemanticRegistryGraphNormalizationService(sql=sql)

    out = svc.normalize_legacy_registry_graph(dry_run=True)

    assert out == {
        "dry_run": True,
        "legacy_counts_before": {
            "semantic_registry": 1,
            "semantic_column_map": 3,
            "semantic_relationship": 4,
        },
        "write_steps_executed": 0,
    }
    assert sql.write_calls == []


def test_normalize_legacy_registry_graph_executes_full_remap_sequence() -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses = [
        [{"count": 2}],
        [{"count": 6}],
        [{"count": 8}],
        [{"count": 0}],
        [{"count": 0}],
        [{"count": 0}],
    ]
    svc = SemanticRegistryGraphNormalizationService(sql=sql)

    out = svc.normalize_legacy_registry_graph(dry_run=False)

    assert out == {
        "dry_run": False,
        "legacy_counts_before": {
            "semantic_registry": 2,
            "semantic_column_map": 6,
            "semantic_relationship": 8,
        },
        "legacy_counts_after": {
            "semantic_registry": 0,
            "semantic_column_map": 0,
            "semantic_relationship": 0,
        },
        "write_steps_executed": 12,
    }
    assert len(sql.write_calls) == 12
    assert "CREATE TEMPORARY TABLE _semantic_registry_vertical_remap" in sql.write_calls[1].query
    assert "UPDATE semantic_column_map scm" in sql.write_calls[6].query
    assert "DELETE rel" in sql.write_calls[7].query
    assert "UPDATE semantic_relationship rel" in sql.write_calls[9].query
    assert "DELETE sr" in sql.write_calls[10].query
