from __future__ import annotations

import pytest
from pydantic import ValidationError

import app.services.semantic.semantic_validation as semantic_validation
from app.services.semantic.semantic_llm_schema import BatchOutput
from app.services.semantic.semantic_validation import validate_semantic_suggestion


def test_schema_validation_pass_and_fail() -> None:
    good = {
        "items": [
            {
                "concept_key": "student.first_name",
                "concept_source": "fallback",
                "canonical_match_confidence": 0.0,
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
                "confidence": 0.9,
                "reasons": ["matches samples"],
            }
        ]
    }
    parsed = BatchOutput.model_validate(good)
    assert parsed.items[0].semantic_type.value == "attribute"

    bad = {
        "items": [
            {
                "concept_key": "x",
                "concept_source": "fallback",
                "canonical_match_confidence": 0.0,
                "semantic_type": "badtype",
                "granularity_rank": 0,
                "filter_allowed": True,
                "group_by_allowed": True,
                "aggregation_allowed": True,
                "is_identifier": False,
                "is_metric": False,
                "display_priority": 0,
                "sensitive": False,
                "confidence": 0.3,
                "reasons": [],
            }
        ]
    }
    with pytest.raises(ValidationError):
        BatchOutput.model_validate(bad)


def test_geography_conflict_rule() -> None:
    result = validate_semantic_suggestion(
        output={
            "concept_key": "school.location",
            "semantic_type": "geography",
            "sub_type": "geography.city",
            "entity": "school",
            "granularity_rank": 1,
            "filter_allowed": True,
            "group_by_allowed": True,
            "aggregation_allowed": False,
            "is_identifier": False,
            "is_metric": False,
            "display_priority": 0,
            "sensitive": False,
            "confidence": 0.95,
            "reasons": ["name"],
        },
        card={
            "signals": {
                "contains_county_word": True,
                "all_numeric": False,
                "boolean_like": False,
            }
        },
    )
    assert "geo_city_county_conflict" in result["validation_errors"]
    assert result["is_valid"] is False


def test_metric_mismatch_rule() -> None:
    result = validate_semantic_suggestion(
        output={
            "concept_key": "student.score",
            "semantic_type": "metric",
            "sub_type": None,
            "entity": "student",
            "granularity_rank": 0,
            "filter_allowed": True,
            "group_by_allowed": False,
            "aggregation_allowed": True,
            "is_identifier": False,
            "is_metric": True,
            "display_priority": 0,
            "sensitive": False,
            "confidence": 0.9,
            "reasons": ["numeric"],
        },
        card={
            "samples": ["abc", "123x"],
            "signals": {
                "all_numeric": False,
                "boolean_like": False,
                "contains_county_word": False,
            }
        },
    )
    assert "metric_sample_mismatch" in result["validation_errors"]
    assert result["is_valid"] is False


def test_auto_approve_threshold() -> None:
    result = validate_semantic_suggestion(
        output={
            "concept_key": "STUDENT_ID",
            "semantic_type": "identifier",
            "sub_type": None,
            "entity": "student",
            "granularity_rank": 0,
            "filter_allowed": True,
            "group_by_allowed": True,
            "aggregation_allowed": True,
            "is_identifier": True,
            "is_metric": False,
            "display_priority": 0,
            "sensitive": False,
            "confidence": 0.92,
            "reasons": ["id-like"],
        },
        card={
            "signals": {
                "all_numeric": False,
                "boolean_like": False,
                "contains_county_word": False,
            }
        },
        auto_approve_threshold=0.9,
    )
    assert result["decision_status"] == "auto_approved"
    assert result["aggregation_allowed"] is False
    assert result["group_by_allowed"] is True


def test_metric_samples_empty_not_invalid_if_numeric_type() -> None:
    result = validate_semantic_suggestion(
        output={
            "concept_key": "DAYS_ATTENDED",
            "semantic_type": "metric",
            "sub_type": None,
            "entity": "student",
            "granularity_rank": 0,
            "filter_allowed": True,
            "group_by_allowed": False,
            "aggregation_allowed": True,
            "is_identifier": False,
            "is_metric": True,
            "display_priority": 0,
            "sensitive": False,
            "confidence": 0.9,
            "reasons": ["defaulted_due_to_uncertainty"],
        },
        card={
            "dataType": "DECIMAL(10,2)",
            "samples": [],
            "signals": {
                "all_numeric": False,
                "boolean_like": False,
                "contains_county_word": False,
            },
        },
    )
    assert "metric_sample_mismatch" not in result["validation_errors"]
    assert "metric_samples_missing" not in result["warnings"]


def test_validate_semantic_suggestion_surfaces_unexpected_confidence_parse_errors() -> None:
    class _BadFloat:
        def __float__(self) -> float:
            raise AssertionError("unexpected confidence parse bug")

    with pytest.raises(AssertionError, match="unexpected confidence parse bug"):
        validate_semantic_suggestion(
            output={
                "concept_key": "STUDENT_ID",
                "semantic_type": "identifier",
                "sub_type": None,
                "entity": "student",
                "granularity_rank": 0,
                "filter_allowed": True,
                "group_by_allowed": True,
                "aggregation_allowed": True,
                "is_identifier": True,
                "is_metric": False,
                "display_priority": 0,
                "sensitive": False,
                "confidence": _BadFloat(),
                "reasons": ["id-like"],
            },
            card={"signals": {}},
        )
