from __future__ import annotations

import pytest

from app.services.nlp.nlp_to_vector import build_vector_search_request


def test_build_vector_request_list_course() -> None:
    nlp_response = {
        "workspace_id": "ws1",
        "text": "what courses are available for students in the fall semester",
        "normalized_text": "courses available",
        "domain_hints": [{"domain_id": 9, "confidence": 0.9}],
        "hard_filters": [
            {
                "column_key": "is_fall",
                "op": "=",
                "value": True,
                "value_type": "bool",
                "extra": "drop",
            }
        ],
        "soft_constraints": [
            {"type": "OUTPUT_PREFERENCE", "text": "courses available", "hints": []}
        ],
        "query_intent": {"subject": "course", "action": "LIST"},
    }

    result = build_vector_search_request(nlp_response)
    assert result["domain_ids"] == [9]
    assert result["query"]["text"] == "courses available"
    assert "is_fall" in result["constraints"]["exclude_column_keys"]


def test_build_vector_request_count_adds_expansions() -> None:
    nlp_response = {
        "workspace_id": "ws1",
        "text": "how many AP courses are offered in fall",
        "domain_hints": [9],
        "query_intent": {"subject": "course", "action": "COUNT"},
    }

    result = build_vector_search_request(nlp_response)
    expanded = result["query"]["expanded_text"]
    assert "count" in expanded
    assert "number of" in expanded
    assert "MEASURE" in result["constraints"]["prefer_column_kinds"]


def test_build_vector_request_skips_invalid_domain_hint_ids() -> None:
    result = build_vector_search_request(
        {
            "workspace_id": "ws1",
            "text": "count students",
            "domain_hints": [{"domain_id": "bad"}, {"domain_id": 9, "confidence": 0.8}],
            "query_intent": {"subject": "student", "action": "COUNT"},
        }
    )

    assert result["domain_ids"] == [9]


def test_build_vector_request_surfaces_unexpected_domain_id_errors() -> None:
    class _BrokenDomainId:
        def __int__(self) -> int:
            raise AssertionError("unexpected domain hint conversion failure")

    with pytest.raises(AssertionError, match="unexpected domain hint conversion failure"):
        build_vector_search_request(
            {
                "workspace_id": "ws1",
                "text": "count students",
                "domain_hints": [{"domain_id": _BrokenDomainId(), "confidence": 0.8}],
                "query_intent": {"subject": "student", "action": "COUNT"},
            }
        )
