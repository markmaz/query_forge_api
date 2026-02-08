from __future__ import annotations

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
