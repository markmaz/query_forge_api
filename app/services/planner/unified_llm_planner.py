from __future__ import annotations

import json
from datetime import date
from typing import Any, Dict, Mapping, Optional

from app.config import SEMANTIC_PLAN_LLM_MAX_TOKENS, SEMANTIC_PLAN_LLM_MODEL
from app.config.llm_resolver import build_llm_client_for_role
from app.constants.llm_roles import LLMRole
from app.exceptions.forge_error import ForgeError
from app.services.llm.llm_client import LLMClient
from app.services.llm.prompts_plan_v2 import SLOT_JSON_SCHEMA, build_system_prompt
from app.services.planner_domain.schema_v2 import plan_v2_json_schema


def parse_json_strict(raw: str) -> Dict[str, Any]:
    candidate = _extract_first_json_object(raw)
    if not isinstance(candidate, dict):
        raise ValueError("model output did not include a JSON object")
    slot_hints = candidate.get("slot_hints")
    plan_json_v2 = candidate.get("plan_json_v2")
    if not isinstance(slot_hints, Mapping):
        raise ValueError("missing required top-level key: slot_hints")
    if not isinstance(plan_json_v2, Mapping):
        raise ValueError("missing required top-level key: plan_json_v2")
    return dict(candidate)


def build_plan_and_slots(
    *,
    prompt: str,
    normalized_prompt: str,
    workspace_id: str,
    vertical_norm: str,
    base_domain_id: int,
    domain_name: str | None,
    capabilities_compact: dict,
    conversation_context: dict,
    trace_id: str,
    llm_client: Optional[LLMClient] = None,
    max_tokens: Optional[int] = None,
    llm_id: Optional[int] = None,
) -> dict:
    active_llm = llm_client
    if active_llm is None:
        resolved = build_llm_client_for_role(
            workspace_id=workspace_id,
            role=LLMRole.PLANNER,
            llm_id_override=llm_id,
        )
        active_llm = resolved.client
    llm = active_llm
    system_prompt = build_system_prompt()
    developer_prompt = _build_unified_developer_prompt(
        slot_schema=SLOT_JSON_SCHEMA,
        plan_schema=plan_v2_json_schema(),
    )
    user_prompt = _build_unified_user_prompt(
        prompt=prompt,
        normalized_prompt=normalized_prompt,
        workspace_id=workspace_id,
        vertical_norm=vertical_norm,
        base_domain_id=base_domain_id,
        domain_name=domain_name,
        capabilities_compact=capabilities_compact,
        conversation_context=conversation_context,
    )

    attempt_count = 0
    last_raw = ""
    repaired = False
    first_trace = llm.chat_json_with_trace(
        system_prompt=system_prompt,
        user_prompt=f"{developer_prompt}\n\n{user_prompt}",
        response_format=True,
        max_tokens=max_tokens or int(SEMANTIC_PLAN_LLM_MAX_TOKENS),
    )
    attempt_count += 1
    parsed, raw_payload = _parse_unified_trace(first_trace)
    first_finish_reason = str(first_trace.get("finish_reason") or "").strip().lower()
    if parsed is None:
        last_raw = raw_payload
        repaired = True
        fix_prompt = _build_json_fix_prompt(raw_payload=raw_payload)
        retry_max_tokens = min(
            int(SEMANTIC_PLAN_LLM_MAX_TOKENS),
            max(int(max_tokens or 0), 600),
        )
        second_trace = llm.chat_json_with_trace(
            system_prompt=system_prompt,
            user_prompt=fix_prompt,
            response_format=True,
            max_tokens=retry_max_tokens,
        )
        attempt_count += 1
        parsed, raw_payload = _parse_unified_trace(second_trace)
        second_finish_reason = str(second_trace.get("finish_reason") or "").strip().lower()
        if parsed is None:
            raise ForgeError(
                "plan_domain unified invalid model JSON",
                status_code=502,
                details={
                    "trace_id": trace_id,
                    "llm_raw_json": raw_payload[:12000],
                    "raw": raw_payload[:4000],
                    "finish_reason_first": first_finish_reason,
                    "finish_reason_second": second_finish_reason,
                    "hint": "Model output may be truncated. Increase token budget or disable fast_mode.",
                },
            )
        trace_for_meta = second_trace
    else:
        trace_for_meta = first_trace

    provider_model, provider_tokens = _extract_provider_model_and_tokens(
        trace=trace_for_meta,
        fallback_model=str(getattr(llm, "_model", "") or SEMANTIC_PLAN_LLM_MODEL),
    )
    response: Dict[str, Any] = {
        "slot_hints": dict(parsed.get("slot_hints") or {}),
        "plan_json_v2": dict(parsed.get("plan_json_v2") or {}),
        "llm_raw_json": raw_payload,
        "llm_model": provider_model,
        "llm_tokens": provider_tokens,
        "attempts": attempt_count,
        "repaired": repaired,
        "llm_prompt_trace": {
            "system_prompt": system_prompt,
            "developer_prompt": developer_prompt,
            "user_prompt": user_prompt,
            "response_format": True,
            "max_tokens": max_tokens or int(SEMANTIC_PLAN_LLM_MAX_TOKENS),
        },
    }
    explanation_draft = parsed.get("explanation_draft")
    if isinstance(explanation_draft, str) and explanation_draft.strip():
        response["explanation_draft"] = explanation_draft.strip()
    if isinstance(explanation_draft, Mapping):
        response["explanation_draft"] = dict(explanation_draft)
    if last_raw and response["llm_raw_json"] == "":
        response["llm_raw_json"] = last_raw
    return response


def _build_unified_developer_prompt(*, slot_schema: Mapping[str, Any], plan_schema: Mapping[str, Any]) -> str:
    return (
        "Task: Produce planning slot hints and a PlanV2 object in one response.\n"
        "Output STRICT JSON ONLY. No prose, markdown, comments, or code fences.\n"
        "Required top-level keys:\n"
        "- slot_hints\n"
        "- plan_json_v2\n"
        "Optional top-level key:\n"
        "- explanation_draft (short string)\n"
        "Rules for slot_hints:\n"
        "- Include intent, entity, constraints, time_phrases.\n"
        "- Include subgroups when naturally implied.\n"
        "Rules for plan_json_v2:\n"
        "- schema_version must be 2.\n"
        "- Use ONLY column_key values present in capabilities payload.\n"
        "- Use ONLY metric refs present in capabilities payload.\n"
        "- Never invent or hallucinate column_keys or metric refs.\n"
        "- Never set a filter value to a column_key token (for example 'wt20.school_name').\n"
        "- Treat phrases like 'by <dimension>' or 'grouped by <dimension>' as grouping intent, not equality filters.\n"
        "- If a requested field is unavailable, select the closest allowed alternative.\n"
        "- For list intent, grouping.group_by should align with selected dimensions.\n"
        "- For aggregate intent, include at least one metric when possible.\n"
        "- For prompts containing 'top N' or 'bottom N': set grouping.limit=N and rank by a relevant metric.\n"
        "- For sales prompts, prefer a sales/revenue metric if available.\n"
        "- Interpret relative dates from current_date in input.\n"
        "- For 'this month' and 'last month', use time.time_range='custom' with start_date/end_date and a valid time_column_key.\n"
        "- For 'this year' and 'last year', use a current-date anchored year range or a year filter using current_date.\n"
        "- Base domain is fixed; do not switch domains.\n"
        "Self-check before output:\n"
        "- Validate every column_key against allowed dimensions/filter columns/time columns.\n"
        "- Validate every filter value: never echo a column_key token as a literal value.\n"
        "- If any column_key is disallowed, replace it with the closest allowed key.\n"
        f"slot_hints schema: {json.dumps(dict(slot_schema), ensure_ascii=True)}\n"
        f"plan_json_v2 schema: {json.dumps(dict(plan_schema), ensure_ascii=True)}"
    )


def _build_unified_user_prompt(
    *,
    prompt: str,
    normalized_prompt: str,
    workspace_id: str,
    vertical_norm: str,
    base_domain_id: int,
    domain_name: Optional[str],
    capabilities_compact: Mapping[str, Any],
    conversation_context: Mapping[str, Any],
) -> str:
    payload = {
        "prompt": prompt,
        "normalized_prompt": normalized_prompt,
        "current_date": date.today().isoformat(),
        "workspace_id": workspace_id,
        "vertical_norm": vertical_norm,
        "base_domain_id": int(base_domain_id),
        "domain_name": str(domain_name or ""),
        "allowed": dict(capabilities_compact or {}),
        "conversation_context": dict(conversation_context or {}),
    }
    return (
        "Build slot_hints + plan_json_v2 for this input.\n"
        f"input: {json.dumps(payload, ensure_ascii=True)}\n"
        "Return JSON only."
    )


def _build_json_fix_prompt(*, raw_payload: str) -> str:
    return (
        "Fix your previous output.\n"
        "Return JSON ONLY with top-level keys: slot_hints and plan_json_v2.\n"
        "Do not include markdown or explanation text.\n"
        f"Previous output: {str(raw_payload or '')[:16000]}"
    )


def _parse_unified_trace(trace: Mapping[str, Any]) -> tuple[Optional[Dict[str, Any]], str]:
    raw_payload = str(trace.get("content") or trace.get("raw_text") or "")
    parsed_payload = trace.get("parsed")
    if isinstance(parsed_payload, Mapping):
        try:
            strict = parse_json_strict(json.dumps(dict(parsed_payload), ensure_ascii=True))
            return strict, raw_payload
        except Exception:
            pass
    try:
        strict = parse_json_strict(raw_payload)
        return strict, raw_payload
    except Exception:
        return None, raw_payload


def _extract_first_json_object(raw: str) -> Optional[Dict[str, Any]]:
    text = str(raw or "").strip()
    if text == "":
        return None
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass
    decoder = json.JSONDecoder()
    for idx, ch in enumerate(text):
        if ch != "{":
            continue
        try:
            parsed, _ = decoder.raw_decode(text[idx:])
        except Exception:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def _extract_provider_model_and_tokens(*, trace: Mapping[str, Any], fallback_model: str) -> tuple[str, Dict[str, Any]]:
    model = str(fallback_model or "").strip() or "unknown"
    usage: Dict[str, Any] = {}
    raw_text = str(trace.get("raw_text") or "").strip()
    if raw_text:
        try:
            provider_body = json.loads(raw_text)
        except Exception:
            provider_body = None
        if isinstance(provider_body, Mapping):
            provider_model = provider_body.get("model")
            if isinstance(provider_model, str) and provider_model.strip():
                model = provider_model.strip()
            provider_usage = provider_body.get("usage")
            if isinstance(provider_usage, Mapping):
                usage = dict(provider_usage)
    return model, usage


__all__ = ["build_plan_and_slots", "parse_json_strict"]
