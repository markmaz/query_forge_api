from __future__ import annotations

import pytest

from app.exceptions.forge_error import ForgeError
from app.schemas.feedback_learning import PromptArtifactBundle
from app.services.feedback_learning.evaluator_client import EvaluatorClient


class _FakeLLMClient:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []
        self._model = "gpt-4.1-mini"

    def chat_json_with_trace(self, **kwargs):
        self.calls.append(kwargs)
        if not self._responses:
            raise AssertionError("unexpected llm call")
        return self._responses.pop(0)


def _bundle() -> PromptArtifactBundle:
    return PromptArtifactBundle.model_validate(
        {
            "prompt_feedback_id": 8,
            "workspace_id": "ws-1",
            "user_id": "user-1",
            "trace_id": "trace-8",
            "conversation_id": "pdc_8",
            "prompt": "Show attendance",
            "normalized_prompt": "show attendance",
            "planner_input": {
                "workspace_id": "ws-1",
                "trace_id": "trace-8",
                "conversation_id": "pdc_8",
                "prompt": "Show attendance",
                "normalized_prompt": "show attendance",
                "meta": {},
            },
            "planner_output": {
                "trace_id": "trace-8",
                "conversation_id": "pdc_8",
                "plan_json_v2": {"base_domain_id": 6},
                "validation": {"is_valid": True, "errors": [], "repairs_applied": []},
                "explanation": {"summary": "attendance"},
                "next_actions": [],
            },
            "generated_sql": {"version": 1, "domainId": 6},
            "output_json": {"trace_id": "trace-8", "conversation_id": "pdc_8"},
        }
    )


def test_evaluator_client_returns_valid_analysis_without_retry() -> None:
    client = EvaluatorClient(
        llm_client=_FakeLLMClient(
            [
                {
                    "content": '{"verdict":"inconclusive","failure_modes":[],"root_causes":[],"proposed_changes":[],"confidence":0.61}',
                    "parsed": {
                        "verdict": "inconclusive",
                        "failure_modes": [],
                        "root_causes": [],
                        "proposed_changes": [],
                        "confidence": 0.61,
                    },
                }
            ]
        ),
        max_retries=2,
    )

    result = client.analyze_failure_with_trace(_bundle())

    assert result.analysis.verdict == "inconclusive"
    assert result.attempts == 1
    assert result.model == "gpt-4.1-mini"


def test_evaluator_client_retries_invalid_schema_then_succeeds() -> None:
    llm = _FakeLLMClient(
        [
            {
                "content": '{"verdict":"planner_error"}',
                "parsed": {"verdict": "planner_error"},
            },
            {
                "content": '{"verdict":"domain_error","failure_modes":["missing_alias"],"root_causes":[{"type":"semantic_gap","target":"student_name","evidence":"alias missing"}],"proposed_changes":[],"confidence":0.91}',
                "parsed": {
                    "verdict": "domain_error",
                    "failure_modes": ["missing_alias"],
                    "root_causes": [
                        {"type": "semantic_gap", "target": "student_name", "evidence": "alias missing"}
                    ],
                    "proposed_changes": [],
                    "confidence": 0.91,
                },
            },
        ]
    )
    client = EvaluatorClient(llm_client=llm, max_retries=1)

    result = client.analyze_failure_with_trace(_bundle())

    assert result.analysis.verdict == "domain_error"
    assert result.attempts == 2
    assert "did not match the required JSON schema" in llm.calls[1]["user_prompt"]


def test_evaluator_client_raises_after_retry_budget_exhausted() -> None:
    client = EvaluatorClient(
        llm_client=_FakeLLMClient(
            [
                {"content": "not-json", "parsed": None},
                {"content": '{"verdict":"planner_error"}', "parsed": {"verdict": "planner_error"}},
            ]
        ),
        max_retries=1,
    )

    with pytest.raises(ForgeError) as exc_info:
        client.analyze_failure_with_trace(_bundle())

    assert exc_info.value.status_code == 502
    assert exc_info.value.details["attempts"] == 2
