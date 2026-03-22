from __future__ import annotations

from typing import Any, Dict, List, Optional

import pytest

from app.exceptions.forge_error import ForgeError
from app.services.semantic.semantic_suggestion_service import SemanticSuggestionService
from tests._support.fakes import FakeForgeQueryPort


class _StubCardService:
    def __init__(self, cards: List[Dict[str, Any]]) -> None:
        self._cards = cards
        self._served = False

    def count_columns(self, *, workspace_table_id: Optional[int] = None) -> int:
        del workspace_table_id
        return len(self._cards)

    def build_column_cards(self, *, offset: int, limit: int, workspace_table_id: Optional[int] = None) -> List[Dict[str, Any]]:
        del limit, workspace_table_id
        if self._served or offset > 0:
            return []
        self._served = True
        return list(self._cards)


class _StubLabeler:
    def __init__(self, outputs: List[Dict[str, Any]]) -> None:
        self._outputs = outputs

    def label_cards(self, *, cards: List[Dict[str, Any]], vertical: Optional[str], known_concepts: Optional[List[Dict[str, Any]]] = None):
        del cards, vertical, known_concepts
        return list(self._outputs), [None for _ in self._outputs]


class _FailingLabeler:
    def __init__(self) -> None:
        self.last_batch_raw: List[Dict[str, Any]] = []

    def label_cards(self, *, cards: List[Dict[str, Any]], vertical: Optional[str], known_concepts: Optional[List[Dict[str, Any]]] = None):
        del vertical, known_concepts
        raw = {
            "attempt1": {"raw_text": "not-json", "parsed": None, "error": "schema_validation_error:json_parse_error"},
            "attempt2": {"raw_text": "{\"items\":[]}", "parsed": {"items": []}, "error": "schema_validation_error:length_mismatch:0:1"},
        }
        self.last_batch_raw = [raw for _ in cards]
        return [None for _ in cards], ["schema_validation_error:json_parse_error" for _ in cards]


def _run_row(status: str = "created") -> Dict[str, Any]:
    return {
        "id": 1,
        "workspace_id": None,
        "vertical": "education",
        "vertical_norm": "education",
        "status": status,
        "params_json": '{"page_size": 100}',
        "total_columns": 0,
        "processed_columns": 0,
        "valid_items": 0,
        "invalid_items": 0,
        "auto_approved_items": 0,
        "approved_items": 0,
        "rejected_items": 0,
        "applied_items": 0,
        "failed_apply_items": 0,
        "error_message": None,
        "started_at": None,
        "completed_at": None,
        "created_by": "user-1",
        "created_at": "2026-02-01",
        "updated_at": "2026-02-01",
    }


def test_execution_flow_with_mocked_llm() -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses = [
        [_run_row(status="created")],
        [],
        [],
        [
            {
                "total": 1,
                "valid_items": 1,
                "invalid_items": 0,
                "auto_approved_items": 1,
                "approved_items": 0,
                "rejected_items": 0,
                "applied_items": 0,
                "failed_apply_items": 0,
            }
        ],
        [_run_row(status="completed")],
    ]

    cards = [
        {
            "workspaceColumnId": 10,
            "workspaceTableId": 2,
            "tableName": "students",
            "columnName": "first_name",
            "dataType": "STRING",
            "description": "student first name",
            "samples": ["Alice", "Bob"],
            "signals": {
                "all_numeric": False,
                "boolean_like": False,
                "date_like": False,
                "contains_county_word": False,
                "unique_ratio_estimate": None,
            },
        }
    ]

    outputs = [
        {
            "concept_key": "student.first_name",
            "semantic_type": "attribute",
            "sub_type": "attribute.student.first_name",
            "entity": "student",
            "granularity_rank": 0,
            "filter_allowed": True,
            "group_by_allowed": True,
            "aggregation_allowed": False,
            "is_identifier": False,
            "is_metric": False,
            "display_priority": 10,
            "sensitive": False,
            "confidence": 0.95,
            "reasons": ["sample values are names"],
        }
    ]

    svc = SemanticSuggestionService(
        sql=sql,
        card_service=_StubCardService(cards),
        labeler=_StubLabeler(outputs),
        batch_size=10,
    )

    run = svc.execute_run(1)
    assert run["status"] == "completed"
    assert any("INSERT INTO semantic_suggestion_item" in call.query for call in sql.write_calls)


def test_cannot_approve_invalid_item() -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses = [
        [
            {
                "id": 7,
                "run_id": 1,
                "model_column_id": 10,
                "model_table_id": 2,
                "table_name": "students",
                "column_name": "first_name",
                "data_type": "STRING",
                "description": None,
                "samples_json": "[]",
                "signals_json": "{}",
                "llm_raw_json": None,
                "proposed_concept_key": None,
                "proposed_semantic_type": None,
                "proposed_sub_type": None,
                "proposed_entity": None,
                "proposed_granularity_rank": 0,
                "proposed_filter_allowed": 1,
                "proposed_group_by_allowed": 1,
                "proposed_aggregation_allowed": 1,
                "proposed_is_identifier": 0,
                "proposed_is_metric": 0,
                "proposed_display_priority": 0,
                "proposed_sensitive": 0,
                "confidence": 0.2,
                "reasons_json": "[]",
                "warnings_json": "[]",
                "validation_errors_json": '["schema_error"]',
                "is_valid": 0,
                "decision_status": "pending",
                "decision_reason": None,
                "applied_at": None,
                "created_at": "2026-02-01",
                "updated_at": "2026-02-01",
            }
        ]
    ]

    svc = SemanticSuggestionService(sql=sql)
    with pytest.raises(ForgeError, match="Cannot approve invalid item"):
        svc.update_item(7, {"decision_status": "approved"})


def test_apply_idempotency() -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses = [
        [_run_row(status="completed")],
        [
            {
                "id": 11,
                "run_id": 1,
                "model_column_id": 44,
                "model_table_id": 3,
                "table_name": "students",
                "column_name": "student_id",
                "data_type": "STRING",
                "description": "id",
                "samples_json": "[]",
                "signals_json": "{}",
                "llm_raw_json": "{}",
                "proposed_concept_key": "student.id",
                "proposed_semantic_type": "identifier",
                "proposed_sub_type": None,
                "proposed_entity": "student",
                "proposed_granularity_rank": 0,
                "proposed_filter_allowed": 1,
                "proposed_group_by_allowed": 1,
                "proposed_aggregation_allowed": 0,
                "proposed_is_identifier": 1,
                "proposed_is_metric": 0,
                "proposed_display_priority": 0,
                "proposed_sensitive": 0,
                "confidence": 0.9,
                "reasons_json": "[]",
                "warnings_json": "[]",
                "validation_errors_json": "[]",
                "is_valid": 1,
                "decision_status": "approved",
                "decision_reason": None,
                "applied_at": None,
                "created_at": "2026-02-01",
                "updated_at": "2026-02-01",
            }
        ],
        [{"total": 1, "valid_items": 1, "invalid_items": 0, "auto_approved_items": 0, "approved_items": 0, "rejected_items": 0, "applied_items": 1, "failed_apply_items": 0}],
        [_run_row(status="completed")],
        [_run_row(status="applied")],
        [_run_row(status="applied")],
        [],
        [{"total": 1, "valid_items": 1, "invalid_items": 0, "auto_approved_items": 0, "approved_items": 0, "rejected_items": 0, "applied_items": 1, "failed_apply_items": 0}],
        [_run_row(status="applied")],
        [_run_row(status="applied")],
    ]

    svc = SemanticSuggestionService(sql=sql)
    upsert_calls = {"registry": 0, "mapping": 0}

    def _fake_upsert_registry(*, run, item):
        del run, item
        upsert_calls["registry"] += 1
        return 101

    def _fake_upsert_mapping(*, run, item, semantic_registry_id):
        del run, item, semantic_registry_id
        upsert_calls["mapping"] += 1
        return None

    svc._upsert_registry = _fake_upsert_registry  # type: ignore[assignment]
    svc._upsert_mapping = _fake_upsert_mapping  # type: ignore[assignment]

    first = svc.apply_approved(1)
    second = svc.apply_approved(1)

    assert first["status"] == "applied"
    assert second["status"] == "applied"
    assert upsert_calls["registry"] == 1
    assert upsert_calls["mapping"] == 1


def test_llm_raw_json_saved_on_schema_failure() -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses = [
        [_run_row(status="created")],
        [],
        [],
        [
            {
                "total": 1,
                "valid_items": 0,
                "invalid_items": 1,
                "auto_approved_items": 0,
                "approved_items": 0,
                "rejected_items": 0,
                "applied_items": 0,
                "failed_apply_items": 0,
            }
        ],
        [_run_row(status="completed")],
    ]
    cards = [
        {
            "workspaceColumnId": 22,
            "workspaceTableId": 2,
            "tableName": "students",
            "columnName": "bad_col",
            "dataType": "STRING",
            "description": "bad",
            "samples": [],
            "signals": {
                "all_numeric": False,
                "boolean_like": False,
                "date_like": False,
                "contains_county_word": False,
                "unique_ratio_estimate": None,
            },
        }
    ]
    svc = SemanticSuggestionService(
        sql=sql,
        card_service=_StubCardService(cards),
        labeler=_FailingLabeler(),
        batch_size=10,
    )

    svc.execute_run(1)
    insert_calls = [c for c in sql.write_calls if "INSERT INTO semantic_suggestion_item" in c.query]
    assert insert_calls
    params = dict(insert_calls[0].params or {})
    llm_raw = params.get("llm_raw_json")
    assert isinstance(llm_raw, str)
    assert "attempt1" in llm_raw
    assert "attempt2" in llm_raw
    assert "schema_validation_error:json_parse_error" in llm_raw
