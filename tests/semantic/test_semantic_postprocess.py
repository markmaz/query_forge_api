from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.services.semantic.semantic_llm_labeler import SemanticLLMLabeler
from app.services.semantic.semantic_postprocess import apply_deterministic_overrides, normalize_concept_key
from app.services.semantic.semantic_suggestion_service import SemanticSuggestionService
from app.services.semantic.semantic_validation import validate_semantic_suggestion
from tests._support.fakes import FakeSQLExecutor


class _StubCardService:
    def __init__(self, cards: List[Dict[str, Any]]) -> None:
        self._cards = cards
        self._served = False

    def count_columns(self, *, model_table_id: Optional[int] = None) -> int:
        del model_table_id
        return len(self._cards)

    def build_column_cards(self, *, offset: int, limit: int, model_table_id: Optional[int] = None) -> List[Dict[str, Any]]:
        del limit, model_table_id
        if self._served or offset > 0:
            return []
        self._served = True
        return list(self._cards)


class _BadLLMClient:
    def chat_json(self, **kwargs):
        del kwargs
        return {
            "items": [
                {
                    "concept_key": "dim_course.k_course",
                    "concept_source": "fallback",
                    "canonical_match_confidence": 0.0,
                    "semantic_type": "attribute",
                    "sub_type": None,
                    "entity": None,
                    "granularity_rank": 0,
                    "filter_allowed": True,
                    "group_by_allowed": True,
                    "aggregation_allowed": False,
                    "is_identifier": False,
                    "is_metric": False,
                    "display_priority": 0,
                    "sensitive": False,
                    "confidence": 0.6,
                    "reasons": ["columnName_ends_with_id"],
                }
            ]
        }


def _run_row(status: str = "created") -> Dict[str, Any]:
    return {
        "id": 3,
        "workspace_id": "ws1",
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


def test_concept_key_normalization_upper_snake() -> None:
    assert normalize_concept_key("dim_course.k_course") == "K_COURSE"
    assert normalize_concept_key(" school/year ") == "YEAR"


def test_reason_mismatch_endswith_id_detected() -> None:
    result = validate_semantic_suggestion(
        output={
            "concept_key": "TENANT_CODE",
            "semantic_type": "identifier",
            "sub_type": None,
            "entity": None,
            "granularity_rank": 0,
            "filter_allowed": True,
            "group_by_allowed": True,
            "aggregation_allowed": False,
            "is_identifier": True,
            "is_metric": False,
            "display_priority": 0,
            "sensitive": False,
            "confidence": 0.8,
            "reasons": ["columnName ends with _id"],
        },
        card={"columnName": "tenant_code", "signals": {}},
    )
    assert "reason_mismatch_endswith_id" in result["validation_errors"]


def test_override_k_prefix_identifier() -> None:
    proposal = {
        "concept_key": "K_COURSE",
        "semantic_type": "attribute",
        "sub_type": None,
        "entity": None,
        "granularity_rank": 0,
        "filter_allowed": True,
        "group_by_allowed": True,
        "aggregation_allowed": False,
        "is_identifier": False,
        "is_metric": False,
        "display_priority": 0,
        "sensitive": False,
        "confidence": 0.5,
        "reasons": ["defaulted_due_to_uncertainty"],
    }
    card = {"columnName": "k_course", "description": None, "samples": []}
    out, notes = apply_deterministic_overrides(card=card, proposal=proposal)

    assert out["semantic_type"] == "identifier"
    assert out["is_identifier"] is True
    assert out["aggregation_allowed"] is False
    assert out["group_by_allowed"] is True
    assert "deterministic_override:identifier" in notes


def test_override_code_identifier() -> None:
    proposal = {
        "concept_key": "TENANT_CODE",
        "semantic_type": "attribute",
        "sub_type": None,
        "entity": None,
        "granularity_rank": 0,
        "filter_allowed": True,
        "group_by_allowed": True,
        "aggregation_allowed": False,
        "is_identifier": False,
        "is_metric": False,
        "display_priority": 0,
        "sensitive": False,
        "confidence": 0.3,
        "reasons": ["defaulted_due_to_uncertainty"],
    }
    card = {
        "columnName": "tenant_code",
        "description": "Assigned code for district tenant",
        "samples": ["A01", "B07"],
    }
    out, _notes = apply_deterministic_overrides(card=card, proposal=proposal)

    assert out["semantic_type"] == "identifier"
    assert out["is_identifier"] is True
    assert out["confidence"] >= 0.7


def test_time_year_from_samples() -> None:
    proposal = {
        "concept_key": "SCHOOL_YEAR",
        "semantic_type": "attribute",
        "sub_type": None,
        "entity": None,
        "granularity_rank": 2,
        "filter_allowed": True,
        "group_by_allowed": True,
        "aggregation_allowed": True,
        "is_identifier": False,
        "is_metric": False,
        "display_priority": 0,
        "sensitive": False,
        "confidence": 0.4,
        "reasons": ["defaulted_due_to_uncertainty"],
    }
    card = {"columnName": "year", "description": "School year", "samples": ["2022", "2023", "2024"]}
    out, notes = apply_deterministic_overrides(card=card, proposal=proposal)

    assert out["semantic_type"] == "time"
    assert out["sub_type"] == "time.year"
    assert out["granularity_rank"] == 0
    assert out["aggregation_allowed"] is False
    assert "deterministic_override:time_year" in notes


def test_execute_run_stores_normalized_concept_key_and_rewritten_reasons() -> None:
    sql = FakeSQLExecutor()
    sql.query_mappings_responses = [
        [_run_row(status="created")],
        [],
        [],
        [],
        [
            {
                "total": 1,
                "valid_items": 1,
                "invalid_items": 0,
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
            "modelColumnId": 999,
            "modelTableId": 11,
            "tableName": "dim_course",
            "columnName": "k_course",
            "dataType": "string",
            "description": "Course identifier",
            "samples": ["MTH101", "SCI201"],
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
        labeler=SemanticLLMLabeler(llm_client=_BadLLMClient()),
    )

    svc.execute_run(3)

    insert_calls = [c for c in sql.write_calls if "INSERT INTO semantic_suggestion_item" in c.query]
    assert insert_calls
    params = dict(insert_calls[0].params or {})

    assert params["proposed_concept_key"] == "COURSE_ID"
    assert params["proposed_semantic_type"] == "identifier"
    reasons = params["reasons_json"]
    assert isinstance(reasons, str)
    assert "column_name_prefix_k_" in reasons
