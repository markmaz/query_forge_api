# tests/analytics/test_dictionary_enrichment_service.py
from __future__ import annotations

from unittest.mock import MagicMock

from app.services.analytics.dictionary_enrichment_service import DictionaryEnrichmentService


def _make_mysql(col_rows=None):
    mysql = MagicMock()
    tx = MagicMock()
    mysql.transaction.return_value.__enter__ = MagicMock(return_value=tx)
    mysql.transaction.return_value.__exit__ = MagicMock(return_value=False)
    tx.execute_query_mappings.return_value = col_rows or []
    return mysql, tx


def test_enrich_skips_columns_with_existing_descriptions():
    mysql, tx = _make_mysql([
        {"id": 10, "column_name": "id", "model_table_id": 1, "description": "Existing desc"}
    ])
    llm = MagicMock()
    llm.generate.return_value = "Generated"
    svc = DictionaryEnrichmentService(mysql=mysql, llm=llm)

    svc.enrich(
        table_id_by_name={"orders": 1},
        columns=[{"table_name": "orders", "column_name": "id",
                  "data_type": "BIGINT", "is_nullable": False, "comment": None}],
    )

    llm.generate.assert_not_called()


def test_enrich_generates_for_missing_descriptions():
    mysql, tx = _make_mysql([
        {"id": 10, "column_name": "id", "model_table_id": 1, "description": None}
    ])
    llm = MagicMock()
    llm.generate.return_value = "AI generated description"
    svc = DictionaryEnrichmentService(mysql=mysql, llm=llm)

    result = svc.enrich(
        table_id_by_name={"orders": 1},
        columns=[{"table_name": "orders", "column_name": "id",
                  "data_type": "BIGINT", "is_nullable": False, "comment": None}],
    )

    llm.generate.assert_called_once()
    assert tx.execute_write.called
    assert result["enriched"] == 1


def test_enrich_ai_failure_does_not_raise():
    mysql, tx = _make_mysql([
        {"id": 10, "column_name": "id", "model_table_id": 1, "description": None}
    ])
    llm = MagicMock()
    llm.generate.side_effect = RuntimeError("LLM offline")
    svc = DictionaryEnrichmentService(mysql=mysql, llm=llm)

    # Must not raise
    result = svc.enrich(
        table_id_by_name={"orders": 1},
        columns=[{"table_name": "orders", "column_name": "id",
                  "data_type": "BIGINT", "is_nullable": False, "comment": None}],
    )

    assert result["errors"] == 1
    assert result["enriched"] == 0


def test_enrich_overwrites_when_requested():
    mysql, tx = _make_mysql([
        {"id": 10, "column_name": "id", "model_table_id": 1, "description": "Old desc"}
    ])
    llm = MagicMock()
    llm.generate.return_value = "New desc"
    svc = DictionaryEnrichmentService(mysql=mysql, llm=llm)

    result = svc.enrich(
        table_id_by_name={"orders": 1},
        columns=[{"table_name": "orders", "column_name": "id",
                  "data_type": "BIGINT", "is_nullable": False, "comment": None}],
        overwrite=True,
    )

    llm.generate.assert_called_once()
    assert result["enriched"] == 1


def test_enrich_no_llm_returns_zero():
    mysql, tx = _make_mysql([])
    svc = DictionaryEnrichmentService(mysql=mysql, llm=None)

    result = svc.enrich(
        table_id_by_name={"orders": 1},
        columns=[{"table_name": "orders", "column_name": "id",
                  "data_type": "BIGINT", "is_nullable": False, "comment": None}],
    )

    assert result == {"enriched": 0, "errors": 0}
