from __future__ import annotations

from app.services.semantic.semantic_storage_normalization_service import SemanticStorageNormalizationService
from tests._support.fakes import FakeForgeQueryPort


def test_audit_legacy_vertical_rows_counts_each_direct_semantic_table() -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses = [
        [{"count": 3}],
        [{"count": 5}],
        [{"count": 7}],
        [{"count": 11}],
    ]
    svc = SemanticStorageNormalizationService(sql=sql)

    out = svc.audit_legacy_vertical_rows()

    assert out == {
        "semantic_concept": 3,
        "semantic_concept_alias": 5,
        "workspace_column_semantic_concept_map": 7,
        "semantic_value_alias": 11,
    }
    assert "semantic_concept" in sql.query_mappings_calls[0].query
    assert "semantic_concept_alias" in sql.query_mappings_calls[1].query
    assert "workspace_column_semantic_concept_map" in sql.query_mappings_calls[2].query
    assert "semantic_value_alias" in sql.query_mappings_calls[3].query


def test_normalize_legacy_vertical_rows_dry_run_skips_writes() -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses = [
        [{"count": 2}],
        [{"count": 1}],
        [{"count": 0}],
        [{"count": 4}],
    ]
    svc = SemanticStorageNormalizationService(sql=sql)

    out = svc.normalize_legacy_vertical_rows(dry_run=True)

    assert out == {
        "dry_run": True,
        "legacy_counts_before": {
            "semantic_concept": 2,
            "semantic_concept_alias": 1,
            "workspace_column_semantic_concept_map": 0,
            "semantic_value_alias": 4,
        },
        "write_steps_executed": 0,
    }
    assert sql.write_calls == []


def test_normalize_legacy_vertical_rows_executes_all_cleanup_steps() -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses = [
        [{"count": 2}],
        [{"count": 2}],
        [{"count": 1}],
        [{"count": 3}],
        [{"count": 0}],
        [{"count": 0}],
        [{"count": 0}],
        [{"count": 0}],
    ]
    svc = SemanticStorageNormalizationService(sql=sql)

    out = svc.normalize_legacy_vertical_rows(dry_run=False)

    assert out == {
        "dry_run": False,
        "legacy_counts_before": {
            "semantic_concept": 2,
            "semantic_concept_alias": 2,
            "workspace_column_semantic_concept_map": 1,
            "semantic_value_alias": 3,
        },
        "legacy_counts_after": {
            "semantic_concept": 0,
            "semantic_concept_alias": 0,
            "workspace_column_semantic_concept_map": 0,
            "semantic_value_alias": 0,
        },
        "write_steps_executed": 12,
    }
    assert len(sql.write_calls) == 12
    assert "DELETE dup" in sql.write_calls[0].query
    assert "UPDATE semantic_concept" in sql.write_calls[2].query
    assert "UPDATE semantic_concept_alias" in sql.write_calls[5].query
    assert "UPDATE workspace_column_semantic_concept_map" in sql.write_calls[8].query
    assert "UPDATE semantic_value_alias" in sql.write_calls[11].query
