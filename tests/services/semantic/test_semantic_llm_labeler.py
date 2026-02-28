from __future__ import annotations

import json
from typing import Any, Dict

from app.services.semantic.semantic_llm_labeler import SemanticLLMLabeler


class _ContextLimitedLLM:
    def __init__(self) -> None:
        self.calls = 0

    def chat_json_with_trace(self, *, system_prompt: str, user_prompt: str, response_format: bool = True) -> Dict[str, Any]:
        del system_prompt, response_format
        self.calls += 1
        marker = "Input column cards JSON array:\n"
        idx = user_prompt.find(marker)
        if idx == -1:
            return {
                "raw_text": "{\"error\":{\"message\":\"bad prompt\"}}",
                "parsed": {"error": {"message": "bad prompt", "param": "input_tokens", "code": 400}},
                "content": "",
                "error": "schema_validation_error:missing",
            }

        cards_json = user_prompt[idx + len(marker) :].strip()
        cards = json.loads(cards_json)
        if len(cards) > 1:
            err = {
                "error": {
                    "message": "This model's maximum context length is 8192 tokens. parameter=input_tokens",
                    "type": "BadRequestError",
                    "param": "input_tokens",
                    "code": 400,
                }
            }
            return {
                "raw_text": json.dumps(err),
                "parsed": err,
                "content": json.dumps(err),
                "error": "schema_validation_error:missing",
            }

        card = cards[0]
        ok = {
            "items": [
                {
                    "concept_key": str(card.get("columnName") or "UNKNOWN").upper(),
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
            ]
        }
        return {
            "raw_text": json.dumps(ok),
            "parsed": ok,
            "content": json.dumps(ok),
            "error": None,
        }


def test_labeler_splits_on_context_limit() -> None:
    llm = _ContextLimitedLLM()
    labeler = SemanticLLMLabeler(llm_client=llm)

    cards = [
        {"modelColumnId": 1, "columnName": "k_school", "description": "School id", "samples": ["1001"]},
        {"modelColumnId": 2, "columnName": "school_year", "description": "School year", "samples": ["2024"]},
    ]

    outputs, errors = labeler.label_cards(cards=cards, vertical="education", known_concepts=[])

    assert len(outputs) == 2
    assert all(err is None for err in errors)
    assert outputs[0]["concept_key"] == "K_SCHOOL"
    assert outputs[1]["concept_key"] == "SCHOOL_YEAR"
    assert llm.calls >= 3
