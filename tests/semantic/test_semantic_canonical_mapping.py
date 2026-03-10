from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.services.semantic.semantic_concept_matcher import SemanticConceptMatcher
from app.services.semantic.semantic_suggestion_service import SemanticSuggestionService
from tests._support.fakes import FakeForgeQueryPort


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


class _StubLabeler:
    def label_cards(self, *, cards: List[Dict[str, Any]], vertical: Optional[str], known_concepts: Optional[List[Dict[str, Any]]] = None):
        del vertical, known_concepts
        return (
            [
                {
                    "concept_key": str(card["columnName"]),
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
                    "reasons": ["defaulted_due_to_uncertainty"],
                }
                for card in cards
            ],
            [None for _ in cards],
        )


class _StubMatcher:
    def load_known_concepts(self, vertical_norm: str) -> List[Dict[str, Any]]:
        del vertical_norm
        return [
            {"concept_key": "SCHOOL_ID"},
            {"concept_key": "SCHOOL_YEAR"},
            {"concept_key": "CITY"},
        ]

    def load_alias_rules(self, vertical_norm: str) -> List[Dict[str, Any]]:
        del vertical_norm
        return []

    def resolve_pre_llm(
        self,
        *,
        card: Dict[str, Any],
        vertical_norm: str,
        known_concepts: Optional[List[Dict[str, Any]]] = None,
        alias_rules: Optional[List[Dict[str, Any]]] = None,
        alias_conf_threshold: float = 0.75,
    ):
        del vertical_norm, known_concepts, alias_rules, alias_conf_threshold
        col = str(card.get("columnName") or "").lower()
        if col == "k_school":
            return (
                {
                    "concept_key": "SCHOOL_ID",
                    "concept_source": "deterministic",
                    "canonical_match_confidence": 0.97,
                    "semantic_type": "identifier",
                    "sub_type": None,
                    "entity": "school",
                    "granularity_rank": 0,
                    "filter_allowed": True,
                    "group_by_allowed": True,
                    "aggregation_allowed": False,
                    "is_identifier": True,
                    "is_metric": False,
                    "display_priority": 0,
                    "sensitive": False,
                    "confidence": 0.97,
                    "reasons": ["column_name_prefix_k_"],
                },
                ["deterministic_identifier_match"],
            )
        if col == "school_year":
            return (
                {
                    "concept_key": "SCHOOL_YEAR",
                    "concept_source": "deterministic",
                    "canonical_match_confidence": 0.9,
                    "semantic_type": "time",
                    "sub_type": "time.year",
                    "entity": None,
                    "granularity_rank": 0,
                    "filter_allowed": True,
                    "group_by_allowed": True,
                    "aggregation_allowed": False,
                    "is_identifier": False,
                    "is_metric": False,
                    "display_priority": 0,
                    "sensitive": False,
                    "confidence": 0.9,
                    "reasons": ["heuristic_match:school_year"],
                },
                ["heuristic_match:school_year"],
            )
        return None, []

    def enforce_canonical_if_strong(
        self,
        card: Dict[str, Any],
        proposal: Dict[str, Any],
        vertical_norm: str,
        known_concepts: Optional[List[Dict[str, Any]]] = None,
        alias_rules: Optional[List[Dict[str, Any]]] = None,
    ):
        del vertical_norm, known_concepts, alias_rules
        out = dict(proposal)
        if str(out.get("concept_source") or "").lower() == "deterministic":
            return out, []
        col = str(card.get("columnName") or "").lower()
        if col == "k_school":
            out["concept_key"] = "SCHOOL_ID"
            out["concept_source"] = "deterministic"
            out["canonical_match_confidence"] = 0.97
            return out, ["deterministic_identifier_match"]
        if col == "school_year":
            out["concept_key"] = "SCHOOL_YEAR"
            out["concept_source"] = "deterministic"
            out["canonical_match_confidence"] = 0.9
            out["semantic_type"] = "time"
            out["sub_type"] = "time.year"
            return out, ["heuristic_match:school_year"]
        if col == "city":
            out["concept_key"] = "CITY"
            out["concept_source"] = "llm"
            out["canonical_match_confidence"] = 0.7
            return out, []
        return out, []


def _run_row(status: str = "created") -> Dict[str, Any]:
    return {
        "id": 55,
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


def test_llm_canonical_not_in_known_list_flips_to_fallback() -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses = [
        [
            {
                "id": 1,
                "vertical_norm": "education",
                "concept_key": "SCHOOL_YEAR",
                "semantic_type": "time",
                "sub_type": "time.year",
                "entity": "school",
                "description": "Academic year",
                "granularity_rank": 0,
                "filter_allowed": 1,
                "group_by_allowed": 1,
                "aggregation_allowed": 0,
                "is_identifier": 0,
                "is_metric": 0,
                "display_priority": 0,
                "sensitive": 0,
            }
        ],
        [],
    ]
    matcher = SemanticConceptMatcher(sql=sql)
    out, notes = matcher.enforce_canonical_if_strong(
        card={"columnName": "unknown_field", "description": None, "samples": []},
        proposal={
            "concept_key": "NOT_A_REAL_KEY",
            "concept_source": "canonical",
            "canonical_match_confidence": 0.9,
            "semantic_type": "attribute",
        },
        vertical_norm="education",
    )

    assert out["concept_source"] == "fallback"
    assert out["concept_key"] == "UNKNOWN_FIELD"
    assert "llm_canonical_unknown_flipped_to_fallback" in notes


def test_alias_and_heuristic_mapping() -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses = [
        [],
        [
            {
                "id": 3,
                "vertical_norm": "education",
                "concept_key": "STATE_COURSE_CODE",
                "semantic_type": "identifier",
                "sub_type": None,
                "entity": "course",
                "description": "State course code",
                "granularity_rank": 0,
                "filter_allowed": 1,
                "group_by_allowed": 1,
                "aggregation_allowed": 0,
                "is_identifier": 1,
                "is_metric": 0,
                "display_priority": 0,
                "sensitive": 0,
            }
        ],
    ]
    matcher = SemanticConceptMatcher(sql=sql)

    out_alias, _notes_alias = matcher.enforce_canonical_if_strong(
        card={"columnName": "k_school", "description": "", "samples": []},
        proposal={"concept_key": "K_SCHOOL", "concept_source": "fallback", "canonical_match_confidence": 0.0},
        vertical_norm="education",
    )
    out_heuristic, _notes_heuristic = matcher.enforce_canonical_if_strong(
        card={"columnName": "state_course_code", "description": "", "samples": ["C18H81"]},
        proposal={"concept_key": "STATE_COURSE_CODE", "concept_source": "fallback", "canonical_match_confidence": 0.0},
        vertical_norm="education",
    )

    assert out_alias["concept_key"] == "SCHOOL_ID"
    assert out_alias["concept_source"] == "deterministic"
    assert out_heuristic["concept_key"] == "STATE_COURSE_CODE"
    assert out_heuristic["concept_source"] == "deterministic"


def test_execute_run_stores_canonical_concept_fields() -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses = [
        [_run_row(status="created")],
        [{"id": 101}],
        [{"id": 102}],
        [{"id": 103}],
        [
            {
                "total": 3,
                "valid_items": 3,
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
            "modelColumnId": 201,
            "modelTableId": 11,
            "tableName": "dim_school",
            "columnName": "k_school",
            "dataType": "string",
            "description": "School key",
            "samples": ["1001", "1002"],
            "signals": {"all_numeric": False, "boolean_like": False, "date_like": False, "contains_county_word": False, "unique_ratio_estimate": None},
        },
        {
            "modelColumnId": 202,
            "modelTableId": 11,
            "tableName": "dim_school",
            "columnName": "school_year",
            "dataType": "string",
            "description": "School year",
            "samples": ["2023", "2024"],
            "signals": {"all_numeric": False, "boolean_like": False, "date_like": True, "contains_county_word": False, "unique_ratio_estimate": None},
        },
        {
            "modelColumnId": 203,
            "modelTableId": 11,
            "tableName": "dim_school",
            "columnName": "city",
            "dataType": "string",
            "description": "City",
            "samples": ["Austin", "Dallas"],
            "signals": {"all_numeric": False, "boolean_like": False, "date_like": False, "contains_county_word": False, "unique_ratio_estimate": None},
        },
    ]

    svc = SemanticSuggestionService(
        sql=sql,
        card_service=_StubCardService(cards),
        labeler=_StubLabeler(),
        matcher=_StubMatcher(),
    )

    svc.execute_run(55)

    insert_calls = [c for c in sql.write_calls if "INSERT INTO semantic_suggestion_item" in c.query]
    assert len(insert_calls) == 3

    first = dict(insert_calls[0].params or {})
    second = dict(insert_calls[1].params or {})
    third = dict(insert_calls[2].params or {})

    assert first["proposed_concept_key"] == "SCHOOL_ID"
    assert first["proposed_concept_source"] == "deterministic"
    assert first["proposed_concept_id"] == 101
    assert first["proposed_fallback_concept"] == 0

    assert second["proposed_concept_key"] == "SCHOOL_YEAR"
    assert second["proposed_concept_source"] == "deterministic"
    assert second["proposed_concept_id"] == 102

    assert third["proposed_concept_key"] == "CITY"
    assert third["proposed_concept_source"] == "llm"
    assert third["proposed_concept_id"] == 103


def test_alias_override_k_school_to_school_id() -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses = [
        [_run_row(status="created")],
        [
            {
                "id": 500,
                "vertical_norm": "education",
                "concept_key": "SCHOOL_ID",
                "semantic_type": "identifier",
                "sub_type": None,
                "entity": "school",
                "description": "School identifier",
                "granularity_rank": 0,
                "filter_allowed": 1,
                "group_by_allowed": 1,
                "aggregation_allowed": 0,
                "is_identifier": 1,
                "is_metric": 0,
                "display_priority": 0,
                "sensitive": 0,
            }
        ],
        [
            {"alias_key": "k_school", "concept_key": "SCHOOL_ID", "match_kind": "exact", "weight": 1.0},
        ],
        [{"id": 500}],
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
            "modelColumnId": 301,
            "modelTableId": 11,
            "tableName": "dim_school",
            "columnName": "k_school",
            "dataType": "string",
            "description": "School key",
            "samples": ["1001", "1002"],
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
        labeler=_StubLabeler(),
        matcher=SemanticConceptMatcher(sql=sql),
    )
    svc.execute_run(55)

    insert_calls = [c for c in sql.write_calls if "INSERT INTO semantic_suggestion_item" in c.query]
    assert len(insert_calls) == 1
    params = dict(insert_calls[0].params or {})
    assert params["proposed_concept_key"] == "SCHOOL_ID"
    assert params["proposed_concept_source"] == "deterministic"
    assert params["proposed_fallback_concept"] == 0
    assert params["proposed_concept_id"] == 500
    assert "column_name_prefix_k_" in params["reasons_json"]


def test_k_lea_to_lea_id_identifier_prepass() -> None:
    matcher = SemanticConceptMatcher(sql=FakeForgeQueryPort())
    proposal, _notes = matcher.resolve_pre_llm(
        card={"columnName": "k_lea", "description": "", "samples": []},
        vertical_norm="education",
        known_concepts=[],
        alias_rules=[],
    )
    assert proposal is not None
    assert proposal["concept_key"] == "LEA_ID"
    assert proposal["semantic_type"] == "identifier"
    assert proposal["concept_source"] == "deterministic"


def test_k_school_to_school_id_identifier_prepass() -> None:
    matcher = SemanticConceptMatcher(sql=FakeForgeQueryPort())
    proposal, _notes = matcher.resolve_pre_llm(
        card={"columnName": "k_school", "description": "", "samples": []},
        vertical_norm="education",
        known_concepts=[],
        alias_rules=[],
    )
    assert proposal is not None
    assert proposal["concept_key"] == "SCHOOL_ID"
    assert proposal["semantic_type"] == "identifier"
    assert proposal["concept_source"] == "deterministic"


def test_student_id_to_student_id_identifier_prepass() -> None:
    matcher = SemanticConceptMatcher(sql=FakeForgeQueryPort())
    proposal, _notes = matcher.resolve_pre_llm(
        card={"columnName": "student_id", "description": "", "samples": []},
        vertical_norm="education",
        known_concepts=[],
        alias_rules=[],
    )
    assert proposal is not None
    assert proposal["concept_key"] == "STUDENT_ID"
    assert proposal["semantic_type"] == "identifier"
    assert proposal["concept_source"] == "deterministic"


def test_tenant_code_to_tenant_code_identifier_prepass() -> None:
    matcher = SemanticConceptMatcher(sql=FakeForgeQueryPort())
    proposal, _notes = matcher.resolve_pre_llm(
        card={"columnName": "tenant_code", "description": "", "samples": []},
        vertical_norm="education",
        known_concepts=[],
        alias_rules=[],
    )
    assert proposal is not None
    assert proposal["concept_key"] == "TENANT_CODE"
    assert proposal["semantic_type"] == "identifier"
    assert proposal["concept_source"] == "deterministic"
