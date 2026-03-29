"""Conversation-context helpers for the planner domain service.

Functions for building, reading, and merging conversation state between turns.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

from app.services.planner_domain.types import PlanConversationContext

# ---------------------------------------------------------------------------
# Compiled regex constants
# ---------------------------------------------------------------------------

_DANGEROUS_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_FOLLOWUP_EDIT_HINT_RE = re.compile(
    r"\b(sort(ed)?|order(ed)?|arrange(d)?|add|remove|drop|exclude|include|hide|also|now|then|keep|same)\b",
    re.IGNORECASE,
)
_SORT_ONLY_PROMPT_RE = re.compile(
    r"^\s*(also\s+|now\s+|then\s+|please\s+)?(sort|order|arrange)(?:\s+the\s+results)?\s+by\b",
    re.IGNORECASE,
)
_SORT_BY_RE = re.compile(
    r"\b(?:sort|order|arrange)(?:\s+the\s+results)?\s+by\s+(?P<field>[a-z0-9_ \-]+?)(?:\s+(?P<dir>asc|desc|ascending|descending))?\s*$",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Prompt normalization
# ---------------------------------------------------------------------------


def normalize_plan_prompt(prompt: str) -> str:
    text = str(prompt or "")
    text = _DANGEROUS_CHAR_RE.sub(" ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _norm_vertical(vertical_norm: str) -> str:
    token = str(vertical_norm or "generic").strip().lower()
    if token in {"education", "healthcare", "generic"}:
        return token
    return "generic"


def _norm_key(value: Any) -> str:
    return str(value or "").strip().lower()


# ---------------------------------------------------------------------------
# Followup intent detection
# ---------------------------------------------------------------------------


def _prompt_is_followup_edit(*, prompt: str, prior_prompt: str) -> bool:
    text = normalize_plan_prompt(prompt).lower()
    if text == "":
        return False
    if _SORT_ONLY_PROMPT_RE.search(text) is not None:
        return True
    if prior_prompt.strip() == "":
        return False
    if len(text) <= 80 and _FOLLOWUP_EDIT_HINT_RE.search(text) is not None:
        return True
    starter_tokens = ("also ", "now ", "then ", "and ", "only ", "just ")
    return any(text.startswith(token) for token in starter_tokens)


def _prompt_is_sort_only(prompt: str) -> bool:
    token = normalize_plan_prompt(prompt).lower()
    return _SORT_ONLY_PROMPT_RE.search(token) is not None


def _prompt_requests_filter_removal(prompt: str) -> bool:
    token = f" {normalize_plan_prompt(prompt).lower()} "
    return any(
        phrase in token
        for phrase in (" remove filter ", " clear filters ", " without filter ", " no filters ")
    )


# ---------------------------------------------------------------------------
# Conversation context construction
# ---------------------------------------------------------------------------


def _plan_conversation_context_from_state(
    *,
    conversation_id: str,
    prompt: str,
    state: Optional[Mapping[str, Any]],
    force_followup: bool = False,
    seeded_from_client: bool = False,
) -> Optional[PlanConversationContext]:
    if not isinstance(state, Mapping):
        return None
    prior_plan = (
        dict(state.get("plan_json_v2") or {})
        if isinstance(state.get("plan_json_v2"), Mapping)
        else {}
    )
    if not prior_plan:
        return None
    prior_prompt = str(state.get("last_prompt") or "").strip()
    followup_mode = bool(force_followup) or _prompt_is_followup_edit(
        prompt=prompt, prior_prompt=prior_prompt
    )
    return PlanConversationContext(
        conversation_id=str(conversation_id or "").strip(),
        prior_prompt=prior_prompt,
        prior_plan_json_v2=prior_plan,
        prior_vertical_norm=_norm_vertical(str(state.get("vertical_norm") or "generic")),
        followup_mode=followup_mode,
        seeded_from_client=bool(seeded_from_client),
    )


def _bootstrap_conversation_state_from_seed(
    *,
    workspace_id: str,
    user_id: str,
    vertical_norm: str,
    seed_plan_json_v2: Mapping[str, Any],
    seed_last_prompt: str,
) -> Dict[str, Any]:
    plan = dict(seed_plan_json_v2 or {})
    normalized_vertical = _norm_vertical(vertical_norm)
    plan_vertical = _norm_vertical(str(plan.get("vertical_norm") or normalized_vertical))
    prompt = seed_last_prompt
    if prompt == "":
        prompt = str(((plan.get("debug") or {}).get("normalized_prompt") or "")).strip()
    return {
        "workspace_id": workspace_id,
        "user_id": user_id,
        "vertical_norm": plan_vertical,
        "last_prompt": prompt,
        "trace_id": str(plan.get("trace_id") or "").strip(),
        "plan_json_v2": plan,
        "sql_json": {},
    }


def _conversation_context_payload(context: PlanConversationContext) -> Dict[str, Any]:
    plan = dict(context.prior_plan_json_v2 or {})
    scoped_plan = {
        "base_domain_id": plan.get("base_domain_id"),
        "domain_name": plan.get("domain_name"),
        "intent": plan.get("intent"),
        "selects": plan.get("selects"),
        "filters": plan.get("filters"),
        "time": plan.get("time"),
        "grouping": plan.get("grouping"),
    }
    return {
        "conversation_id": context.conversation_id,
        "prior_prompt": context.prior_prompt,
        "prior_plan_v2": scoped_plan,
    }


# ---------------------------------------------------------------------------
# Followup plan merging
# ---------------------------------------------------------------------------


def _merge_followup_plan_with_context(
    *,
    prompt: str,
    candidate_plan: Mapping[str, Any],
    prior_plan: Optional[Mapping[str, Any]],
    capabilities: Mapping[str, Any],
) -> Dict[str, Any]:
    out = dict(candidate_plan or {})
    if not isinstance(prior_plan, Mapping):
        return out
    prompt_norm = normalize_plan_prompt(prompt).lower()
    if (
        _FOLLOWUP_EDIT_HINT_RE.search(prompt_norm) is None
        and _SORT_ONLY_PROMPT_RE.search(prompt_norm) is None
    ):
        return out

    prior = dict(prior_plan)

    if _prompt_is_sort_only(prompt_norm):
        out = _merge_sort_only_followup(
            prompt=prompt_norm,
            candidate_plan=out,
            prior_plan=prior,
            capabilities=capabilities,
        )
        return out

    candidate_filters = [
        dict(item)
        for item in list(out.get("filters") or [])
        if isinstance(item, dict)
    ]
    prior_filters = [
        dict(item)
        for item in list(prior.get("filters") or [])
        if isinstance(item, dict)
    ]
    if (
        len(candidate_filters) == 0
        and len(prior_filters) > 0
        and not _prompt_requests_filter_removal(prompt_norm)
    ):
        out["filters"] = prior_filters

    out_selects = dict(out.get("selects") or {})
    prior_selects = dict(prior.get("selects") or {})
    candidate_dims = [
        dict(item)
        for item in list(out_selects.get("dimensions") or [])
        if isinstance(item, dict)
    ]
    prior_dims = [
        dict(item)
        for item in list(prior_selects.get("dimensions") or [])
        if isinstance(item, dict)
    ]
    if len(candidate_dims) == 0 and len(prior_dims) > 0:
        out_selects["dimensions"] = prior_dims
    out["selects"] = out_selects

    out_grouping = dict(out.get("grouping") or {})
    if len(list(out_grouping.get("group_by") or [])) == 0 and len(prior_dims) > 0:
        out_grouping["group_by"] = [
            str(item.get("column_key") or "").strip()
            for item in prior_dims
            if str(item.get("column_key") or "").strip()
        ]
    out["grouping"] = out_grouping
    return out


def _merge_sort_only_followup(
    *,
    prompt: str,
    candidate_plan: Mapping[str, Any],
    prior_plan: Mapping[str, Any],
    capabilities: Mapping[str, Any],
) -> Dict[str, Any]:
    out = dict(prior_plan or {})
    out["trace_id"] = str(candidate_plan.get("trace_id") or out.get("trace_id") or "")

    candidate_grouping = dict(candidate_plan.get("grouping") or {})
    candidate_order_by = [
        dict(item)
        for item in list(candidate_grouping.get("order_by") or [])
        if isinstance(item, dict)
    ]
    if candidate_order_by:
        grouping = dict(out.get("grouping") or {})
        grouping["order_by"] = candidate_order_by
        out["grouping"] = grouping
        return out

    key, direction = _extract_sort_request_from_prompt(
        prompt=prompt, capabilities=capabilities, fallback_plan=out
    )
    if key == "":
        return dict(candidate_plan or out)

    grouping = dict(out.get("grouping") or {})
    grouping["order_by"] = [{"by": key, "dir": direction}]
    dims = [
        dict(item)
        for item in list((out.get("selects") or {}).get("dimensions") or [])
        if isinstance(item, dict)
    ]
    if len(list(grouping.get("group_by") or [])) == 0 and dims:
        grouping["group_by"] = [
            str(item.get("column_key") or "").strip()
            for item in dims
            if str(item.get("column_key") or "").strip()
        ]
    out["grouping"] = grouping
    return out


# ---------------------------------------------------------------------------
# Sort extraction
# ---------------------------------------------------------------------------


def _extract_sort_request_from_prompt(
    *,
    prompt: str,
    capabilities: Mapping[str, Any],
    fallback_plan: Mapping[str, Any],
) -> Tuple[str, str]:
    token = normalize_plan_prompt(prompt).lower()
    match = _SORT_BY_RE.search(token)
    direction = "asc"
    field_hint = ""
    if match is not None:
        field_hint = str(match.group("field") or "").strip().lower()
        dir_hint = str(match.group("dir") or "").strip().lower()
        if dir_hint in {"desc", "descending"}:
            direction = "desc"
    if field_hint == "":
        return "", direction

    column_key = _resolve_sort_column_key_from_hint(
        field_hint=field_hint,
        capabilities=capabilities,
        fallback_plan=fallback_plan,
    )
    return column_key, direction


def _resolve_sort_column_key_from_hint(
    *,
    field_hint: str,
    capabilities: Mapping[str, Any],
    fallback_plan: Mapping[str, Any],
) -> str:
    hint_tokens = [
        token
        for token in re.split(r"[^a-z0-9]+", field_hint.lower())
        if token and token not in {"the", "a", "an"}
    ]
    if not hint_tokens:
        return ""

    candidate_rows = []
    for row in (
        list(capabilities.get("dimensions") or [])
        + list(capabilities.get("filter_columns") or [])
        + list(capabilities.get("time_columns") or [])
    ):
        if not isinstance(row, Mapping):
            continue
        key = _norm_key(row.get("column_key"))
        if key == "":
            continue
        candidate_rows.append(dict(row))

    selected_keys = {
        _norm_key(item.get("column_key"))
        for item in list((fallback_plan.get("selects") or {}).get("dimensions") or [])
        if isinstance(item, Mapping) and _norm_key(item.get("column_key"))
    }

    best_key = ""
    best_score = -1
    for row in candidate_rows:
        key = _norm_key(row.get("column_key"))
        name = str(row.get("column_name") or "").strip().lower()
        label = str(row.get("label") or "").strip().lower()
        score = sum(2 for token in hint_tokens if token in name or token in label) + sum(
            1 for token in hint_tokens if token in key
        )
        if key in selected_keys:
            score += 2
        if score > best_score:
            best_key = key
            best_score = score
    return best_key if best_score > 0 else ""
