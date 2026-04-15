from __future__ import annotations

from app.services.shared_ai.context import PipelineContext
from app.services.shared_ai.nodes.extract_signals import ExtractSignalsNode
from app.services.shared_ai.nodes.normalize_text import NormalizeTextNode


def _context(prompt: str) -> PipelineContext:
    return PipelineContext(
        pipeline_name="shared_ai_test",
        trace_id="trace-1",
        workspace_id="ws-1",
        user_id="user-1",
        request={"prompt": prompt},
    )


def test_extract_signals_node_emits_planner_signals() -> None:
    context = _context("Show me the eldest student")
    context = NormalizeTextNode().run(context)
    context = ExtractSignalsNode().run(context)

    artifact = context.artifacts["prompt_signals"]
    assert "age_extreme_prompt" in artifact.signals
    assert "student_listing" in artifact.signals
