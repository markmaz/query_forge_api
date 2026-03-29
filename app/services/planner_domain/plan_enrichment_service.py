"""Explanation and next-action orchestration for planner_domain."""
from __future__ import annotations

from time import perf_counter
from typing import Any, Dict, List, Mapping, Sequence

from app.services.planner_domain.pipeline_trace import _add_pipeline_step, _append_pipeline_trace_step
from app.services.planner_domain.types import PlanEnrichmentResult


class PlanEnrichmentService:
    def __init__(self, *, explanation_service: Any, next_actions_service: Any) -> None:
        self._explanation = explanation_service
        self._next_actions = next_actions_service

    def run(
        self,
        *,
        selected_domain_id: int,
        selected_domain_name: str,
        validated_plan_json: Mapping[str, Any],
        capabilities: Mapping[str, Any],
        domain_candidates: Sequence[Mapping[str, Any]],
        ranking_debug: Sequence[Mapping[str, Any]],
        shortlisted_columns: Sequence[Mapping[str, Any]],
        country_debug: Sequence[Any],
        school_year_debug: Sequence[Any],
        semester_debug: Sequence[Any],
        prompt: str,
        next_actions_async: bool,
        profile_steps: List[Dict[str, Any]],
        profile_enabled: bool,
        pipeline_trace: Dict[str, Any],
        trace_capture_enabled: bool,
    ) -> PlanEnrichmentResult:
        t_explanation = perf_counter()
        explanation = self._explanation.build_explanation(
            selected_domain_id=selected_domain_id,
            plan_json=validated_plan_json,
            capabilities=capabilities,
            domain_candidates=domain_candidates,
            ranking_debug=ranking_debug,
            shortlisted_columns=shortlisted_columns,
            norm_debug={
                "country": list(country_debug or []),
                "school_year": list(school_year_debug or []),
                "semester": list(semester_debug or []),
            },
        )
        _add_pipeline_step(
            profile_steps=profile_steps,
            enabled=profile_enabled,
            step="explanation_build",
            label="Build deterministic explanation object",
            started_at=t_explanation,
        )
        t_explanation_polish = perf_counter()
        explanation, explanation_summary_trace = self._explanation.maybe_polish_summary(
            prompt=prompt,
            explanation=explanation,
        )
        _add_pipeline_step(
            profile_steps=profile_steps,
            enabled=profile_enabled,
            step="explanation_polish",
            label="Optionally polish explanation summary with LLM",
            started_at=t_explanation_polish,
        )
        _append_pipeline_trace_step(
            trace=pipeline_trace,
            enabled=trace_capture_enabled,
            step="explanation",
            data={
                "explanation": explanation,
                "explanation_summary_trace": explanation_summary_trace,
            },
        )

        if next_actions_async:
            next_actions: List[Any] = []
            next_actions_trace: Any = {"enabled": True, "used": False, "deferred": True}
            _add_pipeline_step(
                profile_steps=profile_steps,
                enabled=profile_enabled,
                step="next_actions",
                label="Defer next action generation (async)",
                started_at=perf_counter(),
            )
            _append_pipeline_trace_step(
                trace=pipeline_trace,
                enabled=trace_capture_enabled,
                step="next_actions",
                data={"status": "deferred"},
            )
            next_actions_status = "deferred"
        else:
            t_next_actions = perf_counter()
            next_actions, next_actions_trace = self._next_actions.maybe_generate(
                prompt=prompt,
                selected_domain_id=selected_domain_id,
                selected_domain_name=str(validated_plan_json.get("domain_name") or "").strip() or selected_domain_name,
                plan_json=dict(validated_plan_json or {}),
                capabilities=dict(capabilities or {}),
            )
            _add_pipeline_step(
                profile_steps=profile_steps,
                enabled=profile_enabled,
                step="next_actions",
                label="Generate in-domain next action suggestions",
                started_at=t_next_actions,
            )
            _append_pipeline_trace_step(
                trace=pipeline_trace,
                enabled=trace_capture_enabled,
                step="next_actions",
                data={
                    "status": "ready",
                    "next_actions": next_actions,
                    "next_actions_trace": next_actions_trace,
                },
            )
            next_actions_status = "ready"

        return PlanEnrichmentResult(
            explanation=dict(explanation or {}),
            explanation_summary_trace=explanation_summary_trace,
            next_actions=list(next_actions or []),
            next_actions_trace=next_actions_trace,
            next_actions_status=next_actions_status,
        )
