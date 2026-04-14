"""Conversation persistence and trace finalization for planner_domain."""
from __future__ import annotations

import logging
from time import perf_counter
from typing import Any, Dict, List, Mapping

from valkey.exceptions import ValkeyError

from app.services.planner_domain.conversation_store import build_conversation_state
from app.services.planner_domain.pipeline_trace import _add_pipeline_step, _elapsed_ms

logger = logging.getLogger(__name__)

CONVERSATION_STORE_FALLBACK_ERRORS = (OSError, ValkeyError)


class PlanFinalizationService:
    def __init__(self, *, conversation_store: Any, conversation_ttl_seconds: int, pipeline_trace_service: Any) -> None:
        self._conversation_store = conversation_store
        self._conversation_ttl_seconds = conversation_ttl_seconds
        self._pipeline_trace = pipeline_trace_service

    def finalize(
        self,
        *,
        workspace_id: str,
        user_id: str,
        normalized_prompt: str,
        trace_id: str,
        conversation_id: str,
        plan_json_v2: Mapping[str, Any],
        sql_json: Mapping[str, Any],
        profile_steps: List[Dict[str, Any]],
        profile_enabled: bool,
        trace_capture_enabled: bool,
        pipeline_trace: Dict[str, Any],
        timings: Dict[str, int],
        started_at: float,
        fast_mode: bool,
        planner_unified_llm: bool,
        planner_compact_enabled: bool,
        response: Dict[str, Any],
    ) -> Dict[str, Any]:
        state = build_conversation_state(
            workspace_id=workspace_id,
            user_id=str(user_id),
            prompt=normalized_prompt,
            trace_id=trace_id,
            plan_json_v2=dict(plan_json_v2 or {}),
            sql_json=dict(sql_json or {}),
        )
        t_state_save = perf_counter()
        try:
            self._conversation_store.save_state(
                workspace_id=workspace_id,
                user_id=str(user_id),
                conversation_id=conversation_id,
                state=state,
                qf_ttl_seconds=self._conversation_ttl_seconds,
            )
        except CONVERSATION_STORE_FALLBACK_ERRORS as exc:
            logger.warning("planner_domain conversation save failed conversation_id=%s err=%s", conversation_id, exc)

        _add_pipeline_step(
            profile_steps=profile_steps,
            enabled=profile_enabled,
            step="conversation_state_save",
            label="Persist conversation state for follow-up context",
            started_at=t_state_save,
        )
        timings["total"] = _elapsed_ms(started_at)
        self._pipeline_trace.emit_profile_log(
            enabled=profile_enabled,
            trace_id=trace_id,
            workspace_id=workspace_id,
            user_id=str(user_id),
            conversation_id=conversation_id,
            prompt=normalized_prompt,
            total_ms=int(timings.get("total") or 0),
            steps=profile_steps,
        )
        self._pipeline_trace.emit_trace_log(
            enabled=trace_capture_enabled,
            trace_payload={
                **pipeline_trace,
                "timings_ms": dict(timings),
                "technical_details": {
                    "trace_id": trace_id,
                    "conversation_id": conversation_id,
                    "fast_mode": fast_mode,
                    "planner_unified_llm": bool(planner_unified_llm),
                    "planner_compact_enabled": bool(planner_compact_enabled),
                },
            },
        )
        if trace_capture_enabled:
            response["technical_details"]["pipeline_trace_enabled"] = True
            response["technical_details"]["pipeline_trace_log_file"] = self._pipeline_trace.trace_log_path()
        if "pipeline_profile" in response:
            response["pipeline_profile"] = list(profile_steps)
        debug_payload = response.get("debug")
        if isinstance(debug_payload, dict):
            if profile_enabled:
                debug_payload["pipeline_profile"] = list(profile_steps)
        return response
