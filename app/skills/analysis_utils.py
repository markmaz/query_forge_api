"""
app/skills/analysis_utils.py

Shared LLM analysis utilities used by both:
  - AISummaryDigestSkill (scheduled email digest)
  - QueryAnalysisAPI (inline query builder analysis)

Extracting these prevents prompt drift between the two surfaces.
Both use identical system prompts and the same structured response format.
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Sampling limits — hard caps applied before any LLM call
# ---------------------------------------------------------------------------

MAX_SAMPLE_ROWS = 200          # max rows passed to build_analysis_user_prompt
MAX_PAYLOAD_BYTES = 50_000     # max serialized sample size (50KB)
MAX_STRING_VALUE_LEN = 200     # truncate long cell values to this length
MAX_PROFILE_CATEGORIES = 5     # top N values shown in categorical profile


# ---------------------------------------------------------------------------
# Response format both surfaces expect from the LLM
# ---------------------------------------------------------------------------

ANALYSIS_RESPONSE_SCHEMA = {
    "narrative": str,
    "highlights": list,
}


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------


def build_analysis_system_prompt(hint: str = "", include_comparison: bool = False) -> str:
    """
    System prompt for query result analysis.
    Used by both the digest skill and the inline analysis endpoint.

    Note: include_comparison=True is only valid for the digest skill,
    which has access to previous run snapshots. The inline analysis
    endpoint always passes include_comparison=False.
    """
    hint_line = f"\nAdditional guidance from the user: {hint}" if hint else ""
    comparison_line = (
        '\n- "comparison": one sentence comparing to previous run data provided, else null'
        if include_comparison else
        '\n- "comparison": null (omit comparison — no prior run available)'
    )

    return (
        "You are a data analyst writing a concise business insight from query results. "
        "You will receive a dataset profile and a sample of rows. "
        "Respond ONLY with valid JSON in this exact format:\n"
        '{"narrative": "2-4 paragraph summary", '
        '"highlights": ["insight 1", "insight 2", "insight 3"], '
        '"comparison": null}\n\n'
        "Rules for narrative:\n"
        "- 2-4 concise paragraphs, business audience, plain language\n"
        "- Draw conclusions from the profile statistics, not just the sample rows\n"
        "- Do not invent trends not supported by the data\n"
        "- Do not state causal explanations unless obvious from structure\n\n"
        "Rules for highlights (3-5 items, each under 15 words):\n"
        "- Prefer: dominant categories, outliers, unusual distributions, "
        "missing/null concentrations, dataset structure insights\n"
        "- Each highlight MUST reference a specific value, count, or percentage from the data\n"
        "- Avoid: fabricated trends, causal claims, restating column names, "
        "vague filler like 'the data shows various values'\n"
        "- Bad example: 'Revenue varies across regions'\n"
        "- Good example: 'EMEA accounts for 62% of total revenue ($284K)'\n"
        f"{comparison_line}"
        f"{hint_line}"
    )


# ---------------------------------------------------------------------------
# Dataset profiling
# ---------------------------------------------------------------------------


def build_dataset_profile(
    rows: list[dict],
    column_names: list[str],
    row_count: int,
) -> dict[str, Any]:
    """
    Generate a lightweight statistical profile of query results.
    Injected into the LLM prompt to dramatically improve insight quality.

    Returns a dict with per-column stats:
      - numeric columns: min, max, avg, null_count
      - categorical columns: distinct_count, top_values, null_count
      - date columns: min_date, max_date, null_count

    The profile uses the full rows sample (up to MAX_SAMPLE_ROWS),
    not a sub-sample — it's cheap to compute and gives the LLM
    much better grounding than raw rows alone.
    """
    if not rows or not column_names:
        return {"row_count": row_count, "column_count": len(column_names), "columns": {}}

    profile: dict[str, Any] = {
        "row_count": row_count,
        "sample_rows_analyzed": len(rows),
        "column_count": len(column_names),
        "columns": {},
    }

    for col in column_names:
        values = [row.get(col) for row in rows]
        non_null = [v for v in values if v is not None and v != ""]
        null_count = len(values) - len(non_null)

        col_profile: dict[str, Any] = {"null_count": null_count}

        if not non_null:
            col_profile["type"] = "empty"
            profile["columns"][col] = col_profile
            continue

        # Try numeric
        numeric_vals = []
        for v in non_null:
            try:
                numeric_vals.append(float(v))
            except (TypeError, ValueError):
                pass

        if len(numeric_vals) / len(non_null) >= 0.8:
            # Predominantly numeric column
            col_profile["type"] = "numeric"
            col_profile["min"] = round(min(numeric_vals), 4)
            col_profile["max"] = round(max(numeric_vals), 4)
            col_profile["avg"] = round(sum(numeric_vals) / len(numeric_vals), 4)
            col_profile["zero_count"] = sum(1 for v in numeric_vals if v == 0)
            profile["columns"][col] = col_profile
            continue

        # Try date detection
        if _looks_like_dates(non_null[:5]):
            str_vals = [str(v) for v in non_null]
            str_vals_sorted = sorted(str_vals)
            col_profile["type"] = "date"
            col_profile["min_date"] = str_vals_sorted[0][:19]
            col_profile["max_date"] = str_vals_sorted[-1][:19]
            profile["columns"][col] = col_profile
            continue

        # Categorical
        str_vals = [str(v)[:MAX_STRING_VALUE_LEN] for v in non_null]
        counts: dict[str, int] = {}
        for v in str_vals:
            counts[v] = counts.get(v, 0) + 1

        top = sorted(counts.items(), key=lambda x: x[1], reverse=True)[:MAX_PROFILE_CATEGORIES]
        col_profile["type"] = "categorical"
        col_profile["distinct_count"] = len(counts)
        col_profile["top_values"] = [
            {"value": v, "count": c, "pct": round(c / len(str_vals) * 100, 1)}
            for v, c in top
        ]
        profile["columns"][col] = col_profile

    return profile


def _looks_like_dates(sample_values: list) -> bool:
    """Heuristic: check if values look like ISO date strings."""
    if not sample_values:
        return False
    hits = 0
    for v in sample_values:
        s = str(v)
        if len(s) >= 10 and s[4:5] == "-" and s[7:8] == "-":
            hits += 1
    return hits / len(sample_values) >= 0.6


# ---------------------------------------------------------------------------
# User prompt
# ---------------------------------------------------------------------------


def build_analysis_user_prompt(
    query_name: str,
    column_names: list[str],
    row_count: int,
    rows: list[dict],
    previous_highlights: list[str] | None = None,
    previous_run_date: str | None = None,
    max_sample_rows: int = MAX_SAMPLE_ROWS,
) -> str:
    """
    User prompt for query result analysis.
    Includes dataset profile + sampled rows.
    Applies hard sampling limits before serialization.
    """
    # Apply row limit
    sample = rows[:max_sample_rows]
    truncated = len(rows) > max_sample_rows

    # Truncate long string values in sample
    clean_sample = _truncate_sample_values(sample)

    # Apply payload size limit
    clean_sample = _enforce_payload_limit(clean_sample)

    # Build dataset profile
    profile = build_dataset_profile(sample, column_names, row_count)

    col_list = ", ".join(column_names[:20])
    truncation_note = (
        f"\n(Note: showing {len(clean_sample)} of {row_count} total rows in sample)"
        if truncated else ""
    )

    prev_section = ""
    if previous_highlights and previous_run_date:
        prev_section = (
            f"\nPrevious run ({previous_run_date}) highlights:\n"
            + "\n".join(f"- {h}" for h in previous_highlights)
        )

    return (
        f"Query: {query_name}\n"
        f"Columns: {col_list}\n"
        f"Total rows: {row_count}{truncation_note}\n\n"
        f"Dataset profile:\n{json.dumps(profile, default=str)}\n\n"
        f"Row sample ({len(clean_sample)} rows):\n"
        f"{json.dumps(clean_sample, default=str)}"
        f"{prev_section}"
    )


def _truncate_sample_values(rows: list[dict]) -> list[dict]:
    """Truncate long string values in rows to MAX_STRING_VALUE_LEN."""
    result = []
    for row in rows:
        clean = {}
        for k, v in row.items():
            if isinstance(v, str) and len(v) > MAX_STRING_VALUE_LEN:
                clean[k] = v[:MAX_STRING_VALUE_LEN] + "…"
            else:
                clean[k] = v
        result.append(clean)
    return result


def _enforce_payload_limit(rows: list[dict]) -> list[dict]:
    """
    Trim rows until serialized payload is under MAX_PAYLOAD_BYTES.
    Returns as many rows as fit within the limit.
    """
    if not rows:
        return rows

    serialized = json.dumps(rows, default=str).encode()
    if len(serialized) <= MAX_PAYLOAD_BYTES:
        return rows

    # Binary search for the cutoff point
    lo, hi = 1, len(rows)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if len(json.dumps(rows[:mid], default=str).encode()) <= MAX_PAYLOAD_BYTES:
            lo = mid
        else:
            hi = mid - 1

    logger.debug(
        "Payload limit applied: trimmed from %d to %d rows (>%d bytes)",
        len(rows), lo, MAX_PAYLOAD_BYTES,
    )
    return rows[:lo]


# ---------------------------------------------------------------------------
# LLM call
# ---------------------------------------------------------------------------


def call_analysis_llm(
    workspace_id: int,
    system_prompt: str,
    user_prompt: str,
    max_tokens: int = 600,
) -> dict[str, Any]:
    """
    Call the workspace LLM for analysis.
    Returns {"narrative": str, "highlights": list, "comparison": str|None}.
    Raises on LLM unavailability — callers must handle and fall back.

    SEAM: verify LLMRole.SUMMARIZER exists in app/constants/llm_roles.py.
    If not, use the available default/fallback role.
    """
    from app.config.llm_resolver import build_llm_client_for_role
    from app.constants.llm_roles import LLMRole

    role = getattr(LLMRole, "SUMMARIZER", None) or LLMRole.DEFAULT

    runtime = build_llm_client_for_role(
        workspace_id=workspace_id,
        role=role,
    )

    result = runtime.client.chat_json(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        response_format=True,
        validator=lambda d: (
            isinstance(d, dict)
            and isinstance(d.get("narrative"), str)
            and isinstance(d.get("highlights"), list)
            and len(d.get("highlights", [])) >= 1
        ),
        max_tokens=max_tokens,
    )

    return {
        "narrative": result.get("narrative", ""),
        "highlights": result.get("highlights", []),
        "comparison": result.get("comparison"),
    }


# ---------------------------------------------------------------------------
# Result hash
# ---------------------------------------------------------------------------


def result_hash(rows: list[dict], row_count: int) -> str:
    """
    Produce a stable hash of query results for cache keying.
    Uses first 50 rows + total row count. Server always recomputes this
    from its own execution results — client hash is a hint only.
    """
    import hashlib
    sample = rows[:50]
    payload = json.dumps(
        {"row_count": row_count, "sample": sample},
        default=str,
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:16]
