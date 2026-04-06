from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, Mapping, Optional, Sequence

from pydantic import ValidationError

from app.config import (
    QF_PLAN_DOMAIN_COMPACT_FALLBACK_MODEL,
    QF_PLAN_DOMAIN_COMPACT_MAX_TOKENS,
    QF_PLAN_DOMAIN_COMPACT_REASONING_EFFORT,
    QF_PLAN_DOMAIN_COMPACT_RETRY_MAX_TOKENS,
    SEMANTIC_PLAN_LLM_MAX_TOKENS,
    SEMANTIC_PLAN_LLM_MODEL,
)
from app.config.llm_resolver import build_llm_client_for_role
from app.constants.llm_roles import LLMRole
from app.exceptions.forge_error import ForgeError
from app.services.llm.llm_client import LLMClient
from app.services.llm.prompts_plan_v2 import build_system_prompt
from app.services.planner.planner_prompt_builder import (
    build_compact_semantic_planner_developer_prompt,
    build_compact_semantic_planner_user_prompt,
    build_compact_semantic_retry_prompt,
    compact_semantic_response_format,
)
from app.services.planner.planner_validation_service import PlannerValidationService
from app.services.planner.semantic_candidate_models import (
    CompactSemanticPlan,
    SemanticCandidatePayload,
)
from app.services.planner.semantic_plan_compiler import SemanticPlanCompiler
from app.services.planner.semantic_retrieval_service import SemanticRetrievalService

logger = logging.getLogger(__name__)


def build_compact_plan_and_project(
    *,
    prompt: str,
    normalized_prompt: str,
    workspace_id: str,
    vertical_norm: str,
    base_domain_id: int,
    domain_name: Optional[str],
    capabilities_compact: Mapping[str, Any],
    conversation_context: Mapping[str, Any],
    trace_id: str,
    llm_client: Optional[LLMClient] = None,
    retrieval_service: Optional[SemanticRetrievalService] = None,
    precomputed_candidates: Optional[SemanticCandidatePayload] = None,
    validation_service: Optional[PlannerValidationService] = None,
    compiler: Optional[SemanticPlanCompiler] = None,
    max_tokens: Optional[int] = None,
    fast_mode: bool = False,
    llm_id: Optional[int] = None,
) -> Dict[str, Any]:
    active_seed_llm = llm_client
    if active_seed_llm is None:
        resolved = build_llm_client_for_role(
            workspace_id=workspace_id,
            role=LLMRole.PLANNER,
            llm_id_override=llm_id,
        )
        active_seed_llm = resolved.client
    llm = active_seed_llm
    retrieval = retrieval_service or SemanticRetrievalService()
    validator = validation_service or PlannerValidationService()
    plan_compiler = compiler or SemanticPlanCompiler()

    candidates = precomputed_candidates
    if candidates is None:
        candidates = retrieval.retrieve(
            prompt=normalized_prompt or prompt,
            workspace_id=workspace_id,
            base_domain_id=int(base_domain_id),
            base_domain_name=domain_name,
            vertical_norm=vertical_norm,
            capabilities_compact=capabilities_compact,
            max_per_type=(12 if fast_mode else 20),
        )
    candidate_summary = _candidate_summary(candidates)
    logger.info(
        "planner_semantic_retrieval trace_id=%s workspace_id=%s base_domain_id=%s summary=%s source=%s",
        trace_id,
        workspace_id,
        base_domain_id,
        json.dumps(candidate_summary, ensure_ascii=True),
        str((candidates.metadata or {}).get("semantic_source") or ""),
    )

    requested_max = int(max_tokens or QF_PLAN_DOMAIN_COMPACT_MAX_TOKENS)
    attempt_tokens = max(180, min(requested_max, int(SEMANTIC_PLAN_LLM_MAX_TOKENS)))
    system_prompt = build_system_prompt()
    developer_prompt = build_compact_semantic_planner_developer_prompt()
    user_prompt = build_compact_semantic_planner_user_prompt(
        prompt=prompt,
        normalized_prompt=normalized_prompt,
        workspace_id=workspace_id,
        vertical_norm=vertical_norm,
        candidates=candidates,
        conversation_context=conversation_context,
    )
    response_format = compact_semantic_response_format()
    extra_params = _extra_reasoning_params_for_model(model=str(getattr(llm, "_model", "") or ""))

    attempts = 0
    repaired = False
    traces: list[Mapping[str, Any]] = []
    parsed_plan: Optional[CompactSemanticPlan] = None
    active_llm = llm

    for idx in range(2):
        attempts += 1
        trace = active_llm.chat_json_with_trace(
            system_prompt=system_prompt,
            user_prompt=f"{developer_prompt}\n\n{user_prompt}",
            response_format=response_format,
            max_tokens=attempt_tokens,
            extra_params=extra_params,
        )
        traces.append(trace)
        finish_reason = str(trace.get("finish_reason") or "").strip().lower()
        provider_model, provider_tokens = _extract_provider_model_and_tokens(
            trace=trace,
            fallback_model=str(getattr(active_llm, "_model", "") or SEMANTIC_PLAN_LLM_MODEL),
        )
        logger.info(
            "planner_semantic_llm trace_id=%s attempt=%s model=%s finish_reason=%s tokens=%s",
            trace_id,
            attempts,
            provider_model,
            finish_reason or "unknown",
            json.dumps(provider_tokens or {}, ensure_ascii=True),
        )

        if _is_truncated(trace):
            repaired = True
            if idx == 0:
                logger.warning("planner_semantic_retry trace_id=%s reason=truncation", trace_id)
                candidates = _trim_candidates_for_retry(candidates)
                user_prompt = build_compact_semantic_planner_user_prompt(
                    prompt=prompt,
                    normalized_prompt=normalized_prompt,
                    workspace_id=workspace_id,
                    vertical_norm=vertical_norm,
                    candidates=candidates,
                    conversation_context={},
                )
                attempt_tokens = max(180, min(int(QF_PLAN_DOMAIN_COMPACT_RETRY_MAX_TOKENS), attempt_tokens))
                if QF_PLAN_DOMAIN_COMPACT_FALLBACK_MODEL:
                    active_llm = LLMClient(
                        endpoint=str(getattr(llm, "_endpoint", "") or None),
                        model=QF_PLAN_DOMAIN_COMPACT_FALLBACK_MODEL,
                        timeout_seconds=int(getattr(llm, "_timeout_seconds", 60)),
                        headers=dict(getattr(llm, "_headers", {}) or {}),
                    )
                continue
            raise _planner_truncation_error(
                trace_id=trace_id,
                traces=traces,
                candidate_summary=candidate_summary,
            )

        parsed_plan = _extract_compact_plan(trace)
        if parsed_plan is None:
            repaired = True
            if idx == 0:
                logger.warning("planner_semantic_retry trace_id=%s reason=parse_failed", trace_id)
                repair_prompt = build_compact_semantic_retry_prompt(
                    previous_output=str(trace.get("content") or trace.get("raw_text") or ""),
                    candidates=_trim_candidates_for_retry(candidates),
                )
                user_prompt = repair_prompt
                attempt_tokens = max(180, min(int(QF_PLAN_DOMAIN_COMPACT_RETRY_MAX_TOKENS), attempt_tokens))
                continue
            raise ForgeError(
                "planner_compact_invalid_response",
                status_code=502,
                details={
                    "trace_id": trace_id,
                    "candidate_summary": candidate_summary,
                    "llm_raw_json": str(trace.get("raw_text") or "")[:12000],
                    "finish_reason": str(trace.get("finish_reason") or ""),
                },
            )
        break

    if parsed_plan is None:
        raise _planner_truncation_error(trace_id=trace_id, traces=traces, candidate_summary=candidate_summary)

    parsed_plan = _coerce_relative_time_plan(
        plan=parsed_plan,
        prompt=normalized_prompt or prompt,
        candidates=candidates,
    )

    validation = validator.validate(plan=parsed_plan, candidates=candidates)
    if validation.errors:
        clarification_question = _clarification_question_for_validation_errors(
            errors=validation.errors,
            candidates=candidates,
            prompt=normalized_prompt or prompt,
        )
        raise ForgeError(
            "planner_compact_validation_failed",
            status_code=422,
            details={
                "trace_id": trace_id,
                "errors": validation.errors,
                "warnings": validation.warnings,
                "candidate_summary": candidate_summary,
                "needs_clarification": True,
                "clarification_question": clarification_question,
            },
        )

    compile_result = plan_compiler.compile(
        plan=validation.normalized_plan,
        candidates=candidates,
        trace_id=trace_id,
        workspace_id=workspace_id,
        vertical_norm=vertical_norm,
        base_domain_id=int(base_domain_id),
        base_domain_name=domain_name,
    )
    plan_json_v2 = compile_result.plan_json_v2
    slot_hints = _semantic_plan_to_slot_hints(validation.normalized_plan)

    trace_for_meta = traces[-1] if traces else {}
    llm_model, llm_tokens = _extract_provider_model_and_tokens(
        trace=trace_for_meta,
        fallback_model=str(getattr(active_llm, "_model", "") or SEMANTIC_PLAN_LLM_MODEL),
    )
    output: Dict[str, Any] = {
        "slot_hints": slot_hints,
        "plan_json_v2": plan_json_v2,
        "compact_plan": validation.normalized_plan.model_dump(mode="json", exclude_none=True),
        "needs_clarification": bool(validation.normalized_plan.needs_clarification),
        "clarification_question": validation.normalized_plan.clarification_question,
        "confidence": float(validation.normalized_plan.confidence),
        "candidate_summary": candidate_summary,
        "validation_warnings": validation.warnings + compile_result.warnings,
        "llm_raw_json": str(trace_for_meta.get("content") or trace_for_meta.get("raw_text") or ""),
        "llm_model": llm_model,
        "llm_tokens": llm_tokens,
        "finish_reason": str(trace_for_meta.get("finish_reason") or ""),
        "attempts": attempts,
        "repaired": repaired,
        "planner_mode": "compact_semantic_v2",
        "llm_prompt_trace": {
            "system_prompt": system_prompt,
            "developer_prompt": developer_prompt,
            "user_prompt": user_prompt,
            "response_format": response_format,
            "max_tokens": attempt_tokens,
        },
    }
    semantic_source = str((candidates.metadata or {}).get("semantic_source") or "")
    if semantic_source:
        output["semantic_source"] = semantic_source
    return output


def _candidate_summary(candidates: SemanticCandidatePayload) -> Dict[str, Any]:
    return {
        "domain_count": len(candidates.domain_candidates),
        "metric_count": len(candidates.metric_candidates),
        "dimension_count": len(candidates.dimension_candidates),
        "filter_count": len(candidates.filter_candidates),
        "time_count": len(candidates.time_candidates),
        "value_count": len(candidates.value_candidates),
        "base_domain_key": candidates.base_domain_key,
    }


def _trim_candidates_for_retry(candidates: SemanticCandidatePayload) -> SemanticCandidatePayload:
    return SemanticCandidatePayload(
        prompt=candidates.prompt,
        normalized_prompt=candidates.normalized_prompt,
        workspace_id=candidates.workspace_id,
        vertical_norm=candidates.vertical_norm,
        base_domain_id=candidates.base_domain_id,
        base_domain_key=candidates.base_domain_key,
        domain=candidates.domain,
        domain_candidates=list(candidates.domain_candidates)[:1],
        metric_candidates=list(candidates.metric_candidates)[:8],
        dimension_candidates=list(candidates.dimension_candidates)[:10],
        filter_candidates=list(candidates.filter_candidates)[:10],
        time_candidates=list(candidates.time_candidates)[:4],
        value_candidates=list(candidates.value_candidates)[:12],
        lexical_hints=dict(candidates.lexical_hints or {}),
        planning_rules=list(candidates.planning_rules)[:6],
        metadata=dict(candidates.metadata or {}),
    )


def _semantic_plan_to_slot_hints(plan: CompactSemanticPlan) -> Dict[str, Any]:
    return {
        "intent": str(plan.intent or "list").strip().lower() or "list",
        "entity": "",
        "constraints": [
            {
                "kind": "filter",
                "text": item.field_concept_key,
                "op": item.operator,
                "value_hint": item.value,
                "notes": None,
            }
            for item in plan.filters
        ],
        "time_phrases": [token for token in [plan.time.time_range, plan.time.time_grain] if token],
    }


def _extract_compact_plan(trace: Mapping[str, Any]) -> Optional[CompactSemanticPlan]:
    parsed = trace.get("parsed")
    if isinstance(parsed, Mapping):
        try:
            return CompactSemanticPlan.model_validate(dict(parsed))
        except ValidationError:
            pass
    content = str(trace.get("content") or "").strip()
    if content:
        payload = _extract_first_json_obj(content)
        if isinstance(payload, Mapping):
            try:
                return CompactSemanticPlan.model_validate(dict(payload))
            except ValidationError:
                return None
    return None


def _extract_first_json_obj(raw: str) -> Optional[Dict[str, Any]]:
    text = str(raw or "").strip()
    if text == "":
        return None
    try:
        parsed = json.loads(text)
        if isinstance(parsed, Mapping):
            return dict(parsed)
    except (TypeError, ValueError, json.JSONDecodeError):
        pass
    decoder = json.JSONDecoder()
    for idx, token in enumerate(text):
        if token != "{":
            continue
        try:
            parsed, _ = decoder.raw_decode(text[idx:])
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if isinstance(parsed, Mapping):
            return dict(parsed)
    return None


def _is_truncated(trace: Mapping[str, Any]) -> bool:
    finish_reason = str(trace.get("finish_reason") or "").strip().lower()
    content = str(trace.get("content") or "").strip()
    return finish_reason == "length" and content == ""


def _planner_truncation_error(
    *,
    trace_id: str,
    traces: Sequence[Mapping[str, Any]],
    candidate_summary: Mapping[str, Any],
) -> ForgeError:
    first = traces[0] if len(traces) > 0 else {}
    second = traces[1] if len(traces) > 1 else {}
    return ForgeError(
        "planner_compact_truncation",
        status_code=502,
        details={
            "trace_id": trace_id,
            "candidate_summary": dict(candidate_summary or {}),
            "finish_reason_first": str(first.get("finish_reason") or ""),
            "finish_reason_second": str(second.get("finish_reason") or ""),
            "llm_raw_json": str((second or first).get("raw_text") or "")[:12000],
            "hint": "Planner output was truncated before JSON content was emitted.",
        },
    )


def _extract_provider_model_and_tokens(*, trace: Mapping[str, Any], fallback_model: str) -> tuple[str, Dict[str, Any]]:
    model = str(fallback_model or "").strip() or "unknown"
    usage: Dict[str, Any] = {}
    raw_text = str(trace.get("raw_text") or "").strip()
    if raw_text:
        try:
            provider_body = json.loads(raw_text)
        except json.JSONDecodeError:
            provider_body = None
        if isinstance(provider_body, Mapping):
            provider_model = provider_body.get("model")
            if isinstance(provider_model, str) and provider_model.strip():
                model = provider_model.strip()
            provider_usage = provider_body.get("usage")
            if isinstance(provider_usage, Mapping):
                usage = dict(provider_usage)
    return model, usage


def _extra_reasoning_params_for_model(*, model: str) -> Dict[str, Any]:
    token = str(model or "").strip().lower()
    if not token.startswith("gpt-5"):
        return {}
    effort = str(QF_PLAN_DOMAIN_COMPACT_REASONING_EFFORT or "").strip().lower()
    if effort not in {"minimal", "low", "medium", "high"}:
        return {}
    return {"reasoning_effort": effort}


def _clarification_question_for_validation_errors(
    *,
    errors: Sequence[Mapping[str, Any]],
    candidates: SemanticCandidatePayload,
    prompt: str,
) -> str:
    metric_errors = [row for row in errors if str(row.get("code") or "").strip().lower().startswith("unknown_metric")]
    if metric_errors:
        sales_options = list((candidates.lexical_hints or {}).get("sales") or [])
        if len(sales_options) >= 2 and "sales" in str(prompt or "").lower():
            labels = []
            for key in sales_options[:2]:
                label = next(
                    (
                        str(item.label or "").strip()
                        for item in list(candidates.metric_candidates or [])
                        if str(item.concept_key or "").strip().upper() == str(key or "").strip().upper()
                    ),
                    str(key or "").strip(),
                )
                if label:
                    labels.append(label)
            if len(labels) >= 2:
                return f"Did you mean {labels[0]} or {labels[1]}?"
    return "Can you clarify which metric and grouping fields you want?"


def _coerce_relative_time_plan(
    *,
    plan: CompactSemanticPlan,
    prompt: str,
    candidates: SemanticCandidatePayload,
) -> CompactSemanticPlan:
    relative_token = _relative_token_from_prompt(prompt)
    if relative_token == "":
        return plan

    time_map = {
        str(item.concept_key or "").strip().upper()
        for item in list(candidates.time_candidates or [])
        if str(item.concept_key or "").strip()
    }
    current_time_key = str(plan.time.time_concept_key or "").strip().upper()
    time_range = str(plan.time.time_range or "").strip()
    time_grain = str(plan.time.time_grain or "").strip()
    needs_update = False

    payload = plan.model_dump(mode="json")
    time_payload = dict(payload.get("time") or {})

    if current_time_key and current_time_key not in time_map:
        # Guardrail for local models: avoid invalid time_concept_key when we only have relative-time intent.
        time_payload["time_concept_key"] = None
        needs_update = True

    if time_range == "":
        time_payload["time_range"] = relative_token
        needs_update = True

    if time_grain == "":
        time_payload["time_grain"] = _relative_time_grain(relative_token)
        needs_update = True

    if not needs_update:
        return plan

    payload["time"] = time_payload
    return CompactSemanticPlan.model_validate(payload)


def _relative_token_from_prompt(prompt: str) -> str:
    text = str(prompt or "").strip().lower()
    if text == "":
        return ""
    if re.search(r"\b(this|current)\s+quarter\b", text):
        return "this_quarter"
    if re.search(r"\b(last|previous)\s+quarter\b", text):
        return "last_quarter"
    if re.search(r"\b(this|current)\s+month\b", text):
        return "this_month"
    if re.search(r"\b(last|previous)\s+month\b", text):
        return "last_month"
    if re.search(r"\b(this|current)\s+year\b", text):
        return "this_year"
    if re.search(r"\b(last|previous)\s+year\b", text):
        return "last_year"
    return ""


def _relative_time_grain(relative_token: str) -> str:
    token = str(relative_token or "").strip().lower()
    if "quarter" in token:
        return "quarter"
    if "year" in token:
        return "year"
    return "month"


__all__ = ["build_compact_plan_and_project"]
