"""LLM planning helpers extracted from PlannerDomainService.

Owns: slot extraction, unified/legacy LLM call paths, slot hint merging,
raw plan normalisation.  Has no knowledge of domain selection, normalizers,
or validation — those remain in service.py / dedicated modules.
"""
from __future__ import annotations

import json
from time import perf_counter
from typing import Any, Dict, List, Mapping, Optional, Sequence

from app.config import (
    QF_PLAN_DOMAIN_COMPACT_MAX_TOKENS,
    QF_PLAN_DOMAIN_COMPACT_PLANNER_ENABLED,
    QF_PLAN_DOMAIN_FAST_MODE_PLAN_MAX_TOKENS,
    QF_PLAN_DOMAIN_FAST_MODE_SLOT_MAX_TOKENS,
    SEMANTIC_PLAN_LLM_MAX_TOKENS,
)
from app.exceptions.forge_error import ForgeError
from app.services.llm.prompts_plan_v2 import (
    SLOT_JSON_SCHEMA,
    build_developer_prompt,
    build_json_repair_prompt,
    build_slot_developer_prompt,
    build_slot_user_prompt,
    build_system_prompt,
    build_user_prompt,
)
from app.services.planner.compact_planner import build_compact_plan_and_project
from app.services.planner.unified_llm_planner import build_plan_and_slots
from app.services.planner_domain.conversation_context import _conversation_context_payload
from app.services.planner_domain.pipeline_trace import (
    _add_pipeline_step,
    _append_pipeline_trace_step,
    _capabilities_summary,
)
from app.services.planner_domain.prompt_intents import (
    _dedupe_text_items,
    _extract_subgroup_terms,
    _extract_time_phrases,
    _looks_like_list_students_prompt,
    _prompt_has_subgroup,
)
from app.services.planner_domain.types import (
    LLMExecutionResult,
    LLMPlanResult,
    PlanConversationContext,
    SlotExtractionResult,
)


# ---------------------------------------------------------------------------
# Module-level helpers (local copies — these also live in service.py for the
# rest of that file's usages, copied here to avoid circular imports)
# ---------------------------------------------------------------------------


def _norm_key(value: Any) -> str:
    return str(value or "").strip().lower()


def _to_int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_text_list(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    items = [str(item).strip() for item in value if str(item).strip()]
    return _dedupe_text_items(items)


def _parse_constraints(value: Any) -> List[Dict[str, Any]]:
    if not isinstance(value, list):
        return []
    out: List[Dict[str, Any]] = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        kind = str(item.get("kind") or "unknown").strip().lower() or "unknown"
        text = str(item.get("text") or "").strip()
        op = str(item.get("op") or "unknown").strip().lower() or "unknown"
        value_hint_raw = item.get("value_hint")
        notes_raw = item.get("notes")
        value_hint = str(value_hint_raw).strip() if value_hint_raw not in (None, "") else None
        notes = str(notes_raw).strip() if notes_raw not in (None, "") else None
        if text == "" and value_hint is None:
            continue
        out.append(
            {
                "kind": kind,
                "text": text or str(value_hint or ""),
                "op": op,
                "value_hint": value_hint,
                "notes": notes,
            }
        )
    return out


def _dedupe_constraints(values: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    seen: set[tuple[str, str, str, str, str]] = set()
    for item in values:
        if not isinstance(item, Mapping):
            continue
        kind = str(item.get("kind") or "unknown").strip().lower() or "unknown"
        text = " ".join(str(item.get("text") or "").strip().split())
        op = str(item.get("op") or "unknown").strip().lower() or "unknown"
        value_hint = (
            " ".join(str(item.get("value_hint") or "").strip().split())
            if item.get("value_hint") not in (None, "")
            else ""
        )
        notes = (
            " ".join(str(item.get("notes") or "").strip().split())
            if item.get("notes") not in (None, "")
            else ""
        )
        if text == "" and value_hint == "":
            continue
        key = (kind, text.lower(), op, value_hint.lower(), notes.lower())
        if key in seen:
            continue
        seen.add(key)
        out.append(
            {
                "kind": kind,
                "text": text or value_hint,
                "op": op,
                "value_hint": value_hint or None,
                "notes": notes or None,
            }
        )
    return out


def _looks_like_plan_v2(payload: Dict[str, Any]) -> bool:
    if not isinstance(payload, dict):
        return False
    selects = payload.get("selects")
    if not isinstance(selects, dict):
        return False
    dimensions = selects.get("dimensions")
    metrics = selects.get("metrics")
    if dimensions is not None and not isinstance(dimensions, list):
        return False
    if metrics is not None and not isinstance(metrics, list):
        return False
    filters = payload.get("filters")
    if filters is not None and not isinstance(filters, list):
        return False
    time_block = payload.get("time")
    if time_block is not None and not isinstance(time_block, dict):
        return False
    grouping = payload.get("grouping")
    if grouping is not None and not isinstance(grouping, dict):
        return False
    return True


def _looks_like_slot_payload(payload: Dict[str, Any]) -> bool:
    required = ("intent", "constraints", "time_phrases")
    if not all(key in payload for key in required):
        return False
    constraints = payload.get("constraints")
    if not isinstance(constraints, list):
        return False
    for item in constraints:
        if not isinstance(item, dict):
            return False
        if "kind" not in item or "text" not in item or "op" not in item:
            return False
    if payload.get("subgroups") is not None and not isinstance(payload.get("subgroups"), list):
        return False
    if not isinstance(payload.get("time_phrases"), list):
        return False
    return True


# ---------------------------------------------------------------------------
# LLMPlanningService
# ---------------------------------------------------------------------------


class LLMPlanningService:
    """Owns LLM call paths for slot extraction and plan generation.

    Constructed once per :class:`PlannerDomainService` instance and receives
    all dependencies via constructor injection.
    """

    def __init__(self, *, llm_client: Any) -> None:
        self._llm = llm_client

    # ------------------------------------------------------------------
    # Slot extraction
    # ------------------------------------------------------------------

    def _call_llm_slots(
        self,
        *,
        normalized_prompt: str,
        workspace_id: str,
        vertical_norm: str,
        base_domain_id: int,
        conversation_context: Optional[PlanConversationContext] = None,
        fast_mode: bool = False,
    ) -> SlotExtractionResult:
        system_prompt = build_system_prompt()
        composed_user = (
            f"{build_slot_developer_prompt()}\n\n"
            f"{build_slot_user_prompt(normalized_prompt=normalized_prompt, workspace_id=workspace_id, vertical_norm=vertical_norm, base_domain_id=base_domain_id)}"
        )
        if conversation_context is not None and conversation_context.followup_mode:
            composed_user = (
                f"{composed_user}\n"
                "Conversation context for follow-up turn:\n"
                f"{json.dumps(_conversation_context_payload(conversation_context), ensure_ascii=True)}\n"
                "If current prompt is an edit/follow-up, use prior plan to retain unchanged filters/selections."
            )

        attempts = 0
        last_raw = ""
        max_attempts = 1 if fast_mode else 2
        slot_max_tokens = (
            max(80, min(int(QF_PLAN_DOMAIN_FAST_MODE_SLOT_MAX_TOKENS), int(SEMANTIC_PLAN_LLM_MAX_TOKENS)))
            if fast_mode
            else min(800, SEMANTIC_PLAN_LLM_MAX_TOKENS)
        )
        for _ in range(max_attempts):
            attempts += 1
            trace = self._llm.chat_json_with_trace(
                system_prompt=system_prompt,
                user_prompt=composed_user,
                response_format=True,
                max_tokens=slot_max_tokens,
            )
            parsed = trace.get("parsed") if isinstance(trace.get("parsed"), dict) else None
            raw_content = str(trace.get("content") or trace.get("raw_text") or "")
            last_raw = raw_content
            if parsed is not None and _looks_like_slot_payload(parsed):
                return SlotExtractionResult(payload=parsed, raw_content=raw_content, attempts=attempts, repaired=False)

        if fast_mode:
            fallback_subgroups = _extract_subgroup_terms(normalized_prompt)
            fallback_intent = "list" if _looks_like_list_students_prompt(normalized_prompt) else "unknown"
            fallback_payload = {
                "intent": fallback_intent,
                "entity": "students" if "student" in normalized_prompt.lower() else "",
                "constraints": [
                    {
                        "kind": "demographic",
                        "text": value,
                        "op": "unknown",
                        "value_hint": value,
                        "notes": None,
                    }
                    for value in fallback_subgroups
                ],
                "time_phrases": _extract_time_phrases(normalized_prompt),
            }
            return SlotExtractionResult(payload=fallback_payload, raw_content=last_raw, attempts=attempts, repaired=False)

        repair_prompt = build_json_repair_prompt(schema=SLOT_JSON_SCHEMA, broken_json=last_raw)
        repair_trace = self._llm.chat_json_with_trace(
            system_prompt=system_prompt,
            user_prompt=repair_prompt,
            response_format=True,
            max_tokens=min(1200, max(900, SEMANTIC_PLAN_LLM_MAX_TOKENS)),
        )
        parsed = repair_trace.get("parsed") if isinstance(repair_trace.get("parsed"), dict) else None
        raw_content = str(repair_trace.get("content") or repair_trace.get("raw_text") or "")
        if parsed is not None and _looks_like_slot_payload(parsed):
            return SlotExtractionResult(payload=parsed, raw_content=raw_content, attempts=3, repaired=True)

        fallback_subgroups = _extract_subgroup_terms(normalized_prompt)
        fallback_intent = "list" if _looks_like_list_students_prompt(normalized_prompt) else "unknown"
        fallback_payload = {
            "intent": fallback_intent,
            "entity": "students" if "student" in normalized_prompt.lower() else "",
            "constraints": [
                {
                    "kind": "demographic",
                    "text": value,
                    "op": "unknown",
                    "value_hint": value,
                    "notes": None,
                }
                for value in fallback_subgroups
            ],
            "time_phrases": _extract_time_phrases(normalized_prompt),
        }
        return SlotExtractionResult(payload=fallback_payload, raw_content=raw_content, attempts=3, repaired=True)

    # ------------------------------------------------------------------
    # Unified LLM path (slots + plan in one call)
    # ------------------------------------------------------------------

    def _call_llm_unified(
        self,
        *,
        prompt: str,
        normalized_prompt: str,
        workspace_id: str,
        vertical_norm: str,
        base_domain_id: int,
        domain_name: Optional[str],
        capabilities: Mapping[str, Any],
        conversation_context: Optional[PlanConversationContext] = None,
        trace_id: str,
        fast_mode: bool = False,
        grounding_bundle: Any = None,
        compact_planner_enabled: Optional[bool] = None,
    ) -> Dict[str, Any]:
        plan_max_tokens = (
            max(120, min(int(QF_PLAN_DOMAIN_FAST_MODE_PLAN_MAX_TOKENS), int(SEMANTIC_PLAN_LLM_MAX_TOKENS)))
            if fast_mode
            else int(SEMANTIC_PLAN_LLM_MAX_TOKENS)
        )
        if fast_mode:
            slot_max_tokens = max(
                80,
                min(int(QF_PLAN_DOMAIN_FAST_MODE_SLOT_MAX_TOKENS), int(SEMANTIC_PLAN_LLM_MAX_TOKENS)),
            )
            unified_max_tokens = min(
                int(SEMANTIC_PLAN_LLM_MAX_TOKENS),
                max(plan_max_tokens + slot_max_tokens, 420),
            )
        else:
            unified_max_tokens = int(SEMANTIC_PLAN_LLM_MAX_TOKENS)
        conversation_payload = (
            _conversation_context_payload(conversation_context)
            if conversation_context is not None and conversation_context.followup_mode
            else {}
        )
        use_compact_planner = (
            bool(compact_planner_enabled)
            if compact_planner_enabled is not None
            else bool(QF_PLAN_DOMAIN_COMPACT_PLANNER_ENABLED)
        )
        if use_compact_planner:
            compact_max_tokens = min(
                int(SEMANTIC_PLAN_LLM_MAX_TOKENS),
                max(
                    160,
                    min(
                        int(QF_PLAN_DOMAIN_COMPACT_MAX_TOKENS),
                        unified_max_tokens,
                    ),
                ),
            )
            return build_compact_plan_and_project(
                prompt=prompt,
                normalized_prompt=normalized_prompt,
                workspace_id=workspace_id,
                vertical_norm=vertical_norm,
                base_domain_id=base_domain_id,
                domain_name=domain_name,
                capabilities_compact=dict(capabilities or {}),
                conversation_context=conversation_payload,
                trace_id=trace_id,
                llm_client=self._llm,
                precomputed_candidates=(
                    getattr(grounding_bundle, "candidates", None)
                    if grounding_bundle is not None
                    else None
                ),
                max_tokens=compact_max_tokens,
                fast_mode=fast_mode,
            )
        return build_plan_and_slots(
            prompt=prompt,
            normalized_prompt=normalized_prompt,
            workspace_id=workspace_id,
            vertical_norm=vertical_norm,
            base_domain_id=base_domain_id,
            domain_name=domain_name,
            capabilities_compact=dict(capabilities or {}),
            conversation_context=conversation_payload,
            trace_id=trace_id,
            llm_client=self._llm,
            max_tokens=unified_max_tokens,
        )

    def execute_plan_generation(
        self,
        *,
        prompt: str,
        normalized_prompt: str,
        workspace_id: str,
        vertical_norm: str,
        base_domain_id: int,
        domain_name: Optional[str],
        capabilities: Mapping[str, Any],
        shortlisted_columns: Sequence[Mapping[str, Any]],
        schema: Dict[str, Any],
        conversation_context: Optional[PlanConversationContext],
        fast_mode: bool,
        trace_id: str,
        semantic_constraints: Optional[Sequence[Mapping[str, Any]]],
        grounding_bundle: Any,
        compact_capabilities_fn: Any,
        planner_unified_llm: bool,
        compact_planner_enabled: bool,
        profile_pipeline_requested: bool,
        profile_pipeline_data_requested: bool,
        profile_enabled: bool,
        profile_steps: List[Dict[str, Any]],
        pipeline_trace: Dict[str, Any],
        trace_capture_enabled: bool,
    ) -> LLMExecutionResult:
        global QF_PLAN_DOMAIN_COMPACT_PLANNER_ENABLED
        QF_PLAN_DOMAIN_COMPACT_PLANNER_ENABLED = compact_planner_enabled
        timings: Dict[str, int] = {}

        def _run_legacy_llm_path() -> LLMExecutionResult:
            t_slots_local = perf_counter()
            slots_local = self._call_llm_slots(
                normalized_prompt=normalized_prompt,
                workspace_id=workspace_id,
                vertical_norm=vertical_norm,
                base_domain_id=base_domain_id,
                conversation_context=conversation_context,
                fast_mode=fast_mode,
            )
            slot_hints_local = self._merge_slot_hints(
                prompt=normalized_prompt,
                slot_payload=slots_local.payload,
                semantic_constraints=semantic_constraints,
            )
            timings["llm_slots"] = _add_pipeline_step(
                profile_steps=profile_steps,
                enabled=profile_enabled,
                step="llm_slots",
                label="Extract intent/constraints slot hints via LLM",
                started_at=t_slots_local,
            )
            _append_pipeline_trace_step(
                trace=pipeline_trace,
                enabled=trace_capture_enabled,
                step="llm_slots",
                data={
                    "slot_hints": slot_hints_local,
                    "slot_raw_json": slots_local.raw_content,
                    "slot_attempts": slots_local.attempts,
                    "slot_repaired": slots_local.repaired,
                },
            )
            t_caps_compact_local = perf_counter()
            capabilities_llm_local = compact_capabilities_fn(
                capabilities=capabilities,
                shortlisted_columns=shortlisted_columns,
                prompt=normalized_prompt,
                slot_hints=slot_hints_local,
                fast_mode=fast_mode,
            )
            _add_pipeline_step(
                profile_steps=profile_steps,
                enabled=profile_enabled,
                step="capabilities_compaction",
                label="Compact capabilities payload for plan generation",
                started_at=t_caps_compact_local,
            )
            _append_pipeline_trace_step(
                trace=pipeline_trace,
                enabled=trace_capture_enabled,
                step="capabilities_compaction",
                data={
                    "capabilities_llm_summary": _capabilities_summary(capabilities_llm_local),
                    "capabilities_llm": capabilities_llm_local,
                },
            )
            t_llm_local = perf_counter()
            llm_local = self._call_llm_plan(
                normalized_prompt=normalized_prompt,
                workspace_id=workspace_id,
                vertical_norm=vertical_norm,
                base_domain_id=base_domain_id,
                capabilities=capabilities_llm_local,
                schema=schema,
                slot_hints=slot_hints_local,
                conversation_context=conversation_context,
                fast_mode=fast_mode,
            )
            timings["llm"] = _add_pipeline_step(
                profile_steps=profile_steps,
                enabled=profile_enabled,
                step="llm_plan",
                label="Generate PlanV2 with LLM",
                started_at=t_llm_local,
            )
            _append_pipeline_trace_step(
                trace=pipeline_trace,
                enabled=trace_capture_enabled,
                step="llm_plan",
                data={
                    "llm_raw_json": llm_local.raw_content,
                    "llm_attempts": llm_local.attempts,
                    "llm_repaired": llm_local.repaired,
                },
            )
            return LLMExecutionResult(
                slots_result=slots_local,
                slot_hints=slot_hints_local,
                capabilities_llm=capabilities_llm_local,
                llm_result=llm_local,
                unified_trace={},
                timings=dict(timings),
            )

        compact_first_enabled = bool(
            compact_planner_enabled
            and not fast_mode
            and not profile_pipeline_requested
            and not profile_pipeline_data_requested
        )
        if planner_unified_llm or compact_first_enabled:
            t_caps_compact = perf_counter()
            capabilities_llm = compact_capabilities_fn(
                capabilities=capabilities,
                shortlisted_columns=shortlisted_columns,
                prompt=normalized_prompt,
                slot_hints=None,
                fast_mode=fast_mode,
            )
            _add_pipeline_step(
                profile_steps=profile_steps,
                enabled=profile_enabled,
                step="capabilities_compaction",
                label="Compact capabilities payload for plan generation",
                started_at=t_caps_compact,
            )
            _append_pipeline_trace_step(
                trace=pipeline_trace,
                enabled=trace_capture_enabled,
                step="capabilities_compaction",
                data={
                    "capabilities_llm_summary": _capabilities_summary(capabilities_llm),
                    "capabilities_llm": capabilities_llm,
                },
            )
            t_llm = perf_counter()
            try:
                unified_result = self._call_llm_unified(
                    prompt=prompt,
                    normalized_prompt=normalized_prompt,
                    workspace_id=workspace_id,
                    vertical_norm=vertical_norm,
                    base_domain_id=base_domain_id,
                    domain_name=domain_name,
                    capabilities=capabilities_llm,
                    conversation_context=conversation_context,
                    trace_id=trace_id,
                    fast_mode=fast_mode,
                    grounding_bundle=grounding_bundle,
                )
                slot_hints = self._merge_slot_hints(
                    prompt=normalized_prompt,
                    slot_payload=unified_result.get("slot_hints") if isinstance(unified_result.get("slot_hints"), Mapping) else {},
                    semantic_constraints=semantic_constraints,
                )
                llm_result = LLMPlanResult(
                    plan_json=dict(unified_result.get("plan_json_v2") or {}),
                    raw_content=str(unified_result.get("llm_raw_json") or ""),
                    attempts=max(1, _to_int(unified_result.get("attempts")) or 1),
                    repaired=bool(unified_result.get("repaired")),
                )
                slots_result = SlotExtractionResult(
                    payload=dict(unified_result.get("slot_hints") or {}),
                    raw_content=str(unified_result.get("llm_raw_json") or ""),
                    attempts=max(1, _to_int(unified_result.get("attempts")) or 1),
                    repaired=bool(unified_result.get("repaired")),
                )
                unified_trace: Dict[str, Any] = {
                    "llm_model": str(unified_result.get("llm_model") or ""),
                    "llm_tokens": dict(unified_result.get("llm_tokens") or {}),
                }
                if str(unified_result.get("planner_mode") or "").strip():
                    unified_trace["planner_mode"] = str(unified_result.get("planner_mode") or "").strip()
                if "finish_reason" in unified_result:
                    unified_trace["finish_reason"] = unified_result.get("finish_reason")
                if "candidate_summary" in unified_result:
                    unified_trace["candidate_summary"] = unified_result.get("candidate_summary")
                if "validation_warnings" in unified_result:
                    unified_trace["validation_warnings"] = unified_result.get("validation_warnings")
                if "llm_prompt_trace" in unified_result:
                    unified_trace["llm_prompt_trace"] = unified_result.get("llm_prompt_trace")
                if "needs_clarification" in unified_result:
                    unified_trace["needs_clarification"] = bool(unified_result.get("needs_clarification"))
                    unified_trace["clarification_question"] = unified_result.get("clarification_question")
                    unified_trace["confidence"] = unified_result.get("confidence")
                if "explanation_draft" in unified_result:
                    unified_trace["explanation_draft"] = unified_result.get("explanation_draft")
                timings["llm"] = _add_pipeline_step(
                    profile_steps=profile_steps,
                    enabled=profile_enabled,
                    step="llm_unified",
                    label="Generate slots+plan with LLM (unified)",
                    started_at=t_llm,
                )
                _append_pipeline_trace_step(
                    trace=pipeline_trace,
                    enabled=trace_capture_enabled,
                    step="llm_unified",
                    data={
                        "slot_hints": dict(unified_result.get("slot_hints") or {}),
                        "llm_model": str(unified_result.get("llm_model") or ""),
                        "llm_tokens": dict(unified_result.get("llm_tokens") or {}),
                        "finish_reason": unified_result.get("finish_reason"),
                        "attempts": unified_result.get("attempts"),
                        "repaired": unified_result.get("repaired"),
                        "candidate_summary": unified_result.get("candidate_summary"),
                        "validation_warnings": unified_result.get("validation_warnings"),
                        "llm_prompt_trace": unified_result.get("llm_prompt_trace"),
                    },
                )
                return LLMExecutionResult(
                    slots_result=slots_result,
                    slot_hints=slot_hints,
                    capabilities_llm=capabilities_llm,
                    llm_result=llm_result,
                    unified_trace=unified_trace,
                    timings=dict(timings),
                )
            except ForgeError as exc:
                err_msg = str(exc.message or "").strip().lower()
                should_fallback = (
                    "unified invalid model json" in err_msg
                    or "planner_compact_truncation" in err_msg
                    or "planner_compact_invalid_response" in err_msg
                )
                if not should_fallback:
                    raise
                _add_pipeline_step(
                    profile_steps=profile_steps,
                    enabled=profile_enabled,
                    step="llm_unified",
                    label="Generate slots+plan with LLM (unified)",
                    started_at=t_llm,
                )
                unified_trace = {
                    "fallback_to_legacy_llm_path": True,
                    "fallback_reason": str(exc.message or "unified_llm_failed"),
                    "fallback_details": dict(exc.details or {}),
                }
                _append_pipeline_trace_step(
                    trace=pipeline_trace,
                    enabled=trace_capture_enabled,
                    step="llm_unified_fallback",
                    data=unified_trace,
                )
                legacy = _run_legacy_llm_path()
                return LLMExecutionResult(
                    slots_result=legacy.slots_result,
                    slot_hints=legacy.slot_hints,
                    capabilities_llm=legacy.capabilities_llm,
                    llm_result=legacy.llm_result,
                    unified_trace=unified_trace,
                    timings=dict(timings),
                )

        return _run_legacy_llm_path()

    # ------------------------------------------------------------------
    # Slot hint merging
    # ------------------------------------------------------------------

    def _merge_slot_hints(
        self,
        *,
        prompt: str,
        slot_payload: Mapping[str, Any],
        semantic_constraints: Optional[Sequence[Mapping[str, Any]]] = None,
    ) -> Dict[str, Any]:
        slot_intent = str(slot_payload.get("intent") or "unknown").strip().lower() or "unknown"
        constraints = _parse_constraints(slot_payload.get("constraints"))
        semantic_items = _parse_constraints(list(semantic_constraints or []))
        if semantic_items:
            constraints = _dedupe_constraints(constraints + semantic_items)
        subgroups = _parse_text_list(slot_payload.get("subgroups"))
        if constraints:
            constraint_terms = [
                str(item.get("value_hint") or item.get("text") or "").strip()
                for item in constraints
                if str(item.get("value_hint") or item.get("text") or "").strip()
            ]
            subgroups = _dedupe_text_items(subgroups + constraint_terms)
        time_phrases = _parse_text_list(slot_payload.get("time_phrases"))
        entity = str(slot_payload.get("entity") or "").strip().lower()

        if slot_intent == "unknown" and _looks_like_list_students_prompt(prompt):
            slot_intent = "list"
        if _prompt_has_subgroup(prompt):
            subgroups = _dedupe_text_items(subgroups + _extract_subgroup_terms(prompt))
        if not time_phrases:
            time_phrases = _extract_time_phrases(prompt)

        return {
            "intent": slot_intent,
            "entity": entity,
            "subgroups": subgroups,
            "constraints": constraints,
            "time_phrases": time_phrases,
        }

    # ------------------------------------------------------------------
    # Legacy plan call
    # ------------------------------------------------------------------

    def _call_llm_plan(
        self,
        *,
        normalized_prompt: str,
        workspace_id: str,
        vertical_norm: str,
        base_domain_id: int,
        capabilities: Mapping[str, Any],
        schema: Dict[str, Any],
        slot_hints: Mapping[str, Any],
        validation_feedback: str = "",
        retry_hint: str = "",
        conversation_context: Optional[PlanConversationContext] = None,
        fast_mode: bool = False,
    ) -> LLMPlanResult:
        system_prompt = build_system_prompt()
        developer_prompt = build_developer_prompt(
            schema=schema,
            slot_hints=slot_hints,
            validation_feedback=validation_feedback,
            retry_hint=retry_hint,
        )
        user_prompt = build_user_prompt(
            normalized_prompt=normalized_prompt,
            workspace_id=workspace_id,
            vertical_norm=vertical_norm,
            base_domain={"domain_id": int(base_domain_id)},
            capabilities=capabilities,
            schema=schema,
            slot_hints=slot_hints,
        )
        if conversation_context is not None and conversation_context.followup_mode:
            user_prompt = (
                f"{user_prompt}\n"
                "Conversation context for follow-up turn:\n"
                f"{json.dumps(_conversation_context_payload(conversation_context), ensure_ascii=True)}\n"
                "Apply user edits to the prior plan. Preserve prior filters/dimensions unless user explicitly changes them."
            )
        composed_user = f"{developer_prompt}\n\n{user_prompt}"

        attempts = 0
        last_raw = ""
        plan_max_tokens = (
            max(120, min(int(QF_PLAN_DOMAIN_FAST_MODE_PLAN_MAX_TOKENS), int(SEMANTIC_PLAN_LLM_MAX_TOKENS)))
            if fast_mode
            else int(SEMANTIC_PLAN_LLM_MAX_TOKENS)
        )
        max_attempts = 1 if fast_mode else 2
        for _ in range(max_attempts):
            attempts += 1
            trace = self._llm.chat_json_with_trace(
                system_prompt=system_prompt,
                user_prompt=composed_user,
                response_format=True,
                max_tokens=plan_max_tokens,
            )
            parsed = trace.get("parsed") if isinstance(trace.get("parsed"), dict) else None
            raw_content = str(trace.get("content") or trace.get("raw_text") or "")
            last_raw = raw_content
            if parsed is not None and _looks_like_plan_v2(parsed):
                return LLMPlanResult(plan_json=parsed, raw_content=raw_content, attempts=attempts, repaired=False)

        if fast_mode:
            repair_prompt = build_json_repair_prompt(schema=schema, broken_json=last_raw)
            repair_trace = self._llm.chat_json_with_trace(
                system_prompt=system_prompt,
                user_prompt=repair_prompt,
                response_format=True,
                max_tokens=max(120, min(220, plan_max_tokens)),
            )
            parsed = repair_trace.get("parsed") if isinstance(repair_trace.get("parsed"), dict) else None
            raw_content = str(repair_trace.get("content") or repair_trace.get("raw_text") or "")
            if parsed is not None and _looks_like_plan_v2(parsed):
                return LLMPlanResult(plan_json=parsed, raw_content=raw_content, attempts=attempts + 1, repaired=True)
            raise ForgeError("plan_domain invalid model JSON", status_code=502, details={"raw": raw_content[:4000]})

        repair_prompt = build_json_repair_prompt(schema=schema, broken_json=last_raw)
        repair_trace = self._llm.chat_json_with_trace(
            system_prompt=system_prompt,
            user_prompt=repair_prompt,
            response_format=True,
            max_tokens=max(1800, SEMANTIC_PLAN_LLM_MAX_TOKENS),
        )
        parsed = repair_trace.get("parsed") if isinstance(repair_trace.get("parsed"), dict) else None
        raw_content = str(repair_trace.get("content") or repair_trace.get("raw_text") or "")
        if parsed is not None and _looks_like_plan_v2(parsed):
            return LLMPlanResult(plan_json=parsed, raw_content=raw_content, attempts=3, repaired=True)
        raise ForgeError("plan_domain invalid model JSON", status_code=502, details={"raw": raw_content[:4000]})

    # ------------------------------------------------------------------
    # Raw plan normalisation
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_llm_plan(
        *,
        raw_plan: Mapping[str, Any],
        trace_id: str,
        workspace_id: str,
        vertical_norm: str,
        base_domain_id: int,
        base_domain_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        out = dict(raw_plan or {})
        out["schema_version"] = 2
        out["trace_id"] = str(out.get("trace_id") or trace_id)
        out["workspace_id"] = workspace_id
        out["vertical_norm"] = vertical_norm
        out["base_domain_id"] = int(base_domain_id)
        if str(base_domain_name or "").strip():
            out["domain_name"] = str(base_domain_name).strip()
        out.setdefault("intent", "list")
        out.setdefault("selects", {"dimensions": [], "metrics": []})
        out.setdefault("filters", [])
        out.setdefault("time", {})
        out.setdefault("grouping", {"group_by": [], "limit": None, "order_by": []})

        selects = out.get("selects") if isinstance(out.get("selects"), Mapping) else {}
        raw_dims = list(selects.get("dimensions") or []) if isinstance(selects, Mapping) else []
        normalized_dims: List[Dict[str, Any]] = []
        for row in raw_dims:
            if not isinstance(row, Mapping):
                continue
            column_key = _norm_key(row.get("column_key") or row.get("columnKey"))
            if column_key == "":
                continue
            normalized_dims.append({"column_key": column_key})

        raw_metrics = list(selects.get("metrics") or []) if isinstance(selects, Mapping) else []
        normalized_metrics: List[Dict[str, Any]] = []
        for row in raw_metrics:
            if not isinstance(row, Mapping):
                continue
            metric_ref = _norm_key(
                row.get("metric_ref")
                or row.get("metricRef")
                or row.get("metricref")
            )
            if metric_ref == "":
                continue
            normalized_metrics.append({"metric_ref": metric_ref})

        out["selects"] = {
            "dimensions": normalized_dims,
            "metrics": normalized_metrics,
        }
        return out
