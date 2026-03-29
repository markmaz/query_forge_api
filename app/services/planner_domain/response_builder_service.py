"""Response and debug payload assembly for planner_domain."""
from __future__ import annotations

from typing import Any, Dict, Mapping, Optional, Sequence

from app.services.planner_domain.pipeline_trace import _sanitize_pipeline_trace_value


class PlannerResponseBuilderService:
    """Builds final planner responses while preserving payload shape."""

    def build_plan_response(
        self,
        *,
        validated: Any,
        sql_json: Mapping[str, Any],
        explanation: Mapping[str, Any],
        next_actions: Sequence[Mapping[str, Any]] | Sequence[Any],
        next_actions_status: str,
        trace_id: str,
        conversation_id: str,
        fast_mode: bool,
        planner_unified_llm: bool,
        planner_compact_enabled: bool,
        llm_resolution: Mapping[str, Any],
        timings: Mapping[str, Any],
        unified_trace: Mapping[str, Any],
        clarification_question: Optional[str] = None,
        planner_confidence: Optional[float] = None,
        pipeline_profile: Optional[Sequence[Mapping[str, Any]]] = None,
        pipeline_trace_enabled: bool = False,
        pipeline_trace_log_file: Optional[str] = None,
        debug_payload: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        response: Dict[str, Any] = {
            "plan_json_v2": validated.plan_json,
            "sql_json": dict(sql_json or {}),
            "validation": {
                "is_valid": validated.is_valid,
                "errors": validated.issues,
                "repairs_applied": validated.repairs_applied,
            },
            "explanation": dict(explanation or {}),
            "next_actions": list(next_actions or []),
            "next_actions_status": str(next_actions_status or "ready"),
            "trace_id": trace_id,
            "conversation_id": conversation_id,
            "technical_details": {
                "trace_id": trace_id,
                "conversation_id": conversation_id,
                "fast_mode": fast_mode,
                "planner_unified_llm": bool(planner_unified_llm),
                "planner_compact_enabled": bool(planner_compact_enabled),
                "llm_resolution": dict(llm_resolution or {}),
            },
            "timings_ms": dict(timings or {}),
        }
        if bool(unified_trace.get("needs_clarification")):
            response["needs_clarification"] = True
            response["clarification_question"] = str(clarification_question or "").strip() or None
            response["planner_confidence"] = float(planner_confidence or 0.0)
        if pipeline_profile is not None:
            response["pipeline_profile"] = list(pipeline_profile)
        if debug_payload is not None:
            response["debug"] = debug_payload
        if pipeline_trace_enabled:
            response["technical_details"]["pipeline_trace_enabled"] = True
            response["technical_details"]["pipeline_trace_log_file"] = pipeline_trace_log_file
        return response

    def build_debug_payload(
        self,
        *,
        normalized_prompt: str,
        conversation_id: str,
        conversation_context_used: bool,
        followup_mode: bool,
        conversation_seeded_from_client: bool,
        selected_domain_id: Any,
        capabilities: Mapping[str, Any],
        capabilities_llm: Mapping[str, Any],
        domain_candidates: Sequence[Mapping[str, Any]],
        domain_ranking: Sequence[Mapping[str, Any]],
        rerank_signals: Sequence[Any],
        column_shortlist_count: int,
        slot_hints: Mapping[str, Any],
        semantic_assist_enabled: bool,
        semantic_value_alias_constraints: Sequence[Mapping[str, Any]],
        semantic_value_alias_normalization: Any,
        semantic_grounding: Any,
        semester_indicator_columns: Mapping[str, Any],
        slot_raw_json: str,
        slot_attempts: int,
        slot_repaired: bool,
        country_value_normalization: Sequence[Any],
        school_year_value_normalization: Sequence[Any],
        semester_value_normalization: Sequence[Any],
        school_name_filter_normalization: Sequence[Any],
        staff_role_filter_normalization: Sequence[Any],
        adm_filter_normalization: Sequence[Any],
        district_county_retry_hint: str | None,
        llm_raw_json: str,
        llm_attempts: int,
        llm_repaired: bool,
        planner_unified_llm: bool,
        unified_llm_trace: Mapping[str, Any],
        explanation_summary_trace: Any,
        next_actions_trace: Any,
        technical_details: Mapping[str, Any],
        profile_enabled: bool,
        pipeline_profile: Sequence[Mapping[str, Any]],
        trace_capture_enabled: bool,
        pipeline_trace: Mapping[str, Any],
    ) -> Dict[str, Any]:
        debug_payload: Dict[str, Any] = {
            "normalized_prompt": normalized_prompt,
            "conversation_id": conversation_id,
            "conversation_context_used": conversation_context_used,
            "followup_mode": followup_mode,
            "conversation_seeded_from_client": conversation_seeded_from_client,
            "selected_domain_id": selected_domain_id,
            "capabilities": dict(capabilities or {}),
            "capabilities_llm": dict(capabilities_llm or {}),
            "domain_candidates": list(domain_candidates or []),
            "domain_ranking": list(domain_ranking or []),
            "rerank_signals": list(rerank_signals or []),
            "column_shortlist_count": int(column_shortlist_count or 0),
            "slot_hints": dict(slot_hints or {}),
            "semantic_assist_enabled": bool(semantic_assist_enabled),
            "semantic_value_alias_constraints": list(semantic_value_alias_constraints or []),
            "semantic_value_alias_normalization": semantic_value_alias_normalization,
            "semantic_grounding": semantic_grounding,
            "semester_indicator_columns": dict(semester_indicator_columns or {}),
            "slot_raw_json": slot_raw_json,
            "slot_attempts": llm_attempts if slot_attempts is None else slot_attempts,
            "slot_repaired": bool(slot_repaired),
            "country_value_normalization": list(country_value_normalization or []),
            "school_year_value_normalization": list(school_year_value_normalization or []),
            "semester_value_normalization": list(semester_value_normalization or []),
            "school_name_filter_normalization": list(school_name_filter_normalization or []),
            "staff_role_filter_normalization": list(staff_role_filter_normalization or []),
            "adm_filter_normalization": list(adm_filter_normalization or []),
            "district_county_retry_hint": district_county_retry_hint,
            "llm_raw_json": llm_raw_json,
            "llm_attempts": int(llm_attempts or 0),
            "llm_repaired": bool(llm_repaired),
            "planner_unified_llm": bool(planner_unified_llm),
            "unified_llm_trace": dict(unified_llm_trace or {}),
            "explanation_summary_trace": explanation_summary_trace,
            "next_actions_trace": next_actions_trace,
            "technical_details": dict(technical_details or {}),
        }
        if profile_enabled:
            debug_payload["pipeline_profile"] = list(pipeline_profile or [])
        if trace_capture_enabled:
            debug_payload["pipeline_trace"] = _sanitize_pipeline_trace_value(pipeline_trace)
        return debug_payload
