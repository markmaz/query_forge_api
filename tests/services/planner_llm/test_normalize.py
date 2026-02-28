from __future__ import annotations

from app.services.planner_llm.service import normalize_prompt_for_planner


def test_normalize_prompt_for_planner_cleans_without_overpatching() -> None:
    prompt = "  Show   Students per Teacher; by School `Last Year`  "
    normalized = normalize_prompt_for_planner(prompt)
    assert normalized == "show students per teacher by school last year"
