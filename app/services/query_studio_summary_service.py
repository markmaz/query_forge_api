"""
app/services/query_studio_summary_service.py

Stateless AI summary generation for Query Studio run previews.
Calls the shared analysis_utils LLM pipeline with row-capping.
No caching, no email, no digest snapshots — stateless per request.
"""
from __future__ import annotations

import os
import logging

from app.exceptions.forge_error import ForgeError
from app.exceptions.llm_unavailable_error import LLMUnavailableError
from app.skills.analysis_utils import (
    build_analysis_system_prompt,
    build_analysis_user_prompt,
    call_analysis_llm,
)

logger = logging.getLogger(__name__)


def generate_preview_summary(
    workspace_id: str,
    query_name: str,
    column_names: list[str],
    rows: list[dict],
    prompt_hint: str = "",
) -> dict:
    """
    Generate an AI summary of query preview results.

    Caps rows to QUERY_STUDIO_SUMMARY_MAX_ROWS before calling the LLM.
    Always passes the original (uncapped) row count to the user prompt.

    Returns:
        {narrative: str, highlights: list[str], comparison: any, capped: bool}

    Raises:
        LLMUnavailableError: when workspace has no LLM configured (ForgeError status 400/404)
        Any other exception from call_analysis_llm propagates unchanged.
    """
    max_rows = int(os.getenv("QUERY_STUDIO_SUMMARY_MAX_ROWS", 100))
    original_row_count = len(rows)
    capped = original_row_count > max_rows
    capped_rows = rows[:max_rows]

    effective_hint = prompt_hint or ""
    if capped:
        effective_hint = (
            effective_hint
            + f" Note: this summary is based on the first {max_rows} rows of {original_row_count} total."
        ).lstrip()

    system_prompt = build_analysis_system_prompt(
        hint=effective_hint,
        include_comparison=False,
    )
    user_prompt = build_analysis_user_prompt(
        query_name=query_name,
        column_names=column_names,
        row_count=original_row_count,
        rows=capped_rows,
        previous_highlights=None,
        previous_run_date=None,
    )

    try:
        result = call_analysis_llm(
            workspace_id,
            system_prompt,
            user_prompt,
            max_tokens=600,
        )
    except ForgeError as exc:
        # ForgeError 404 = no LLM config found for role
        # ForgeError 400 = LLM misconfigured (missing model/endpoint/api_key)
        # Both represent "workspace LLM not available" from the caller's perspective.
        if exc.status_code in (400, 404):
            raise LLMUnavailableError(str(exc)) from exc
        raise

    return {
        "narrative": str(result.get("narrative") or ""),
        "highlights": list(result.get("highlights") or []),
        "comparison": result.get("comparison") or None,
        "capped": capped,
    }
