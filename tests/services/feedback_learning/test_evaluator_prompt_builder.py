from __future__ import annotations

from app.schemas.feedback_learning import PromptArtifactBundle
from app.services.feedback_learning.evaluator_prompt_builder import EvaluatorPromptBuilder


def _bundle(**overrides):
    payload = {
        "prompt_feedback_id": 4,
        "workspace_id": "ws-1",
        "user_id": "user-1",
        "trace_id": "trace-4",
        "conversation_id": "pdc_4",
        "prompt": "Show me attendance",
        "normalized_prompt": "show me attendance",
        "planner_input": {
            "workspace_id": "ws-1",
            "trace_id": "trace-4",
            "conversation_id": "pdc_4",
            "prompt": "Show me attendance",
            "normalized_prompt": "show me attendance",
            "meta": {"domain_id": 9},
        },
        "planner_output": {
            "trace_id": "trace-4",
            "conversation_id": "pdc_4",
            "plan_json_v2": {"base_domain_id": 9, "intent": "attendance_lookup", "metrics": [], "filters": []},
            "validation": {"is_valid": True, "errors": [], "repairs_applied": []},
            "explanation": {"summary": "attendance"},
            "next_actions": [],
        },
        "generated_sql": {"version": 1, "domainId": 9},
        "output_json": {
            "trace_id": "trace-4",
            "conversation_id": "pdc_4",
            "timings_ms": {"total": 42},
            "explanation": {"summary": "attendance"},
        },
        "candidate_domains": None,
        "candidate_concepts": None,
        "selected_concepts": None,
        "result_preview": None,
    }
    payload.update(overrides)
    return PromptArtifactBundle.model_validate(payload)


def test_prompt_builder_includes_schema_and_summary_fields() -> None:
    builder = EvaluatorPromptBuilder()

    prompts = builder.build_prompts(bundle=_bundle())

    assert '"verdict"' in prompts["system_prompt"]
    assert '"planner_output_summary"' in prompts["user_prompt"]
    assert '"generated_sql"' in prompts["user_prompt"]


def test_prompt_builder_omits_none_optional_sections() -> None:
    builder = EvaluatorPromptBuilder()

    prompts = builder.build_prompts(bundle=_bundle())

    assert '"candidate_domains"' not in prompts["user_prompt"]
    assert '"candidate_concepts"' not in prompts["user_prompt"]
    assert '"selected_concepts"' not in prompts["user_prompt"]
    assert '"result_preview"' not in prompts["user_prompt"]
