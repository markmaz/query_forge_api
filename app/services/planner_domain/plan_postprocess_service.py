"""Post-LLM normalization, validation, and retry orchestration."""
from __future__ import annotations

from time import perf_counter
from typing import Any, Dict, List, Mapping, Optional

from app.services.planner_domain.conversation_context import _merge_followup_plan_with_context
from app.services.planner_domain.domain_metric_binding import bind_prompt_domain_metric
from app.services.planner_domain.llm_planning_service import LLMPlanningService
from app.services.planner_domain.pipeline_trace import _add_pipeline_step, _append_pipeline_trace_step
from app.services.planner_domain.plan_helpers import (
    _district_county_retry_hint,
    _format_validation_feedback,
    _should_retry_after_validation,
)
from app.services.planner_domain.types import LLMPlanResult, PlanConversationContext, PlanPostprocessResult
from app.services.planner_domain.validate_v2 import ValidationResult, validate_and_repair_plan_v2


class PlanPostprocessService:
    """Owns the normalize -> validate -> retry loop after initial LLM generation."""

    def __init__(self, *, llm_planning_service: LLMPlanningService, semantic_integration: Any, normalization_pipeline: Any) -> None:
        self._llm_planning = llm_planning_service
        self._semantic_integration = semantic_integration
        self._normalization = normalization_pipeline

    def _normalize_and_validate(
        self,
        *,
        llm_result: LLMPlanResult,
        trace_id: str,
        workspace_id: str,
        base_domain_id: int,
        base_domain_name: str,
        prompt: str,
        capabilities: Mapping[str, Any],
        conversation_context: Optional[PlanConversationContext],
        semester_indicator_columns: Mapping[str, Any],
        domain_time_policy: Mapping[str, Any],
        profile_steps: List[Dict[str, Any]],
        profile_enabled: bool,
        pipeline_trace: Dict[str, Any],
        trace_capture_enabled: bool,
        step_name: str,
        step_label: str,
    ) -> tuple[ValidationResult, Any, Dict[str, List[Any]], List[Dict[str, Any]]]:
        t_plan_normalize = perf_counter()
        llm_plan = LLMPlanningService._normalize_llm_plan(
            raw_plan=llm_result.plan_json,
            trace_id=trace_id,
            workspace_id=workspace_id,
            base_domain_id=base_domain_id,
            base_domain_name=base_domain_name,
        )
        llm_plan = _merge_followup_plan_with_context(
            prompt=prompt,
            candidate_plan=llm_plan,
            prior_plan=(conversation_context.prior_plan_json_v2 if conversation_context is not None and conversation_context.followup_mode else None),
            capabilities=capabilities,
        )
        llm_plan, semantic_alias_issues, semantic_alias_debug = self._semantic_integration.normalize_semantic_value_alias_filters(
            plan_json=llm_plan,
            workspace_id=workspace_id,
            capabilities=capabilities,
        )
        norm_result = self._normalization.run(
            plan=llm_plan,
            capabilities=capabilities,
            prompt=prompt,
            semester_indicator_columns=semester_indicator_columns,
            domain_time_policy=domain_time_policy,
        )
        llm_plan = bind_prompt_domain_metric(
            plan_json=norm_result.plan,
            capabilities=capabilities,
            prompt=prompt,
        )
        normalization_issues = semantic_alias_issues + norm_result.all_issues
        _add_pipeline_step(
            profile_steps=profile_steps,
            enabled=profile_enabled,
            step=step_name,
            label=step_label,
            started_at=t_plan_normalize,
        )
        _append_pipeline_trace_step(
            trace=pipeline_trace,
            enabled=trace_capture_enabled,
            step=step_name,
            data={
                "normalized_plan_json_v2": llm_plan,
                "normalization_issues": normalization_issues,
                "semantic_value_alias_normalization": semantic_alias_debug,
            },
        )

        t_validate = perf_counter()
        validated = validate_and_repair_plan_v2(
            plan_json=llm_plan,
            capabilities=capabilities,
            prompt=prompt,
            expected_base_domain_id=base_domain_id,
            extra_issues=normalization_issues,
        )
        validate_step_name = "validation_retry" if step_name.startswith("retry") else "validation"
        validate_step_label = "Validate and repair retry plan" if validate_step_name == "validation_retry" else "Validate and repair plan against capabilities"
        validation_elapsed = _add_pipeline_step(
            profile_steps=profile_steps,
            enabled=profile_enabled,
            step=validate_step_name,
            label=validate_step_label,
            started_at=t_validate,
        )
        _append_pipeline_trace_step(
            trace=pipeline_trace,
            enabled=trace_capture_enabled,
            step=validate_step_name,
            data={
                "is_valid": validated.is_valid,
                "issues": validated.issues,
                "repairs_applied": validated.repairs_applied,
                "validated_plan_json_v2": validated.plan_json,
            },
        )
        debug_payload = {
            "country": norm_result.debug.get("country") or [],
            "school_year": norm_result.debug.get("school_year") or [],
            "semester": norm_result.debug.get("semester") or [],
            "school_name": norm_result.debug.get("school_name") or [],
            "staff_role": norm_result.debug.get("staff_role") or [],
            "adm_default": norm_result.debug.get("adm_default") or [],
        }
        return validated, semantic_alias_debug, debug_payload, [{"timing_key": validate_step_name, "ms": validation_elapsed}]

    def run(
        self,
        *,
        llm_result: LLMPlanResult,
        slot_hints: Dict[str, Any],
        capabilities_llm: Mapping[str, Any],
        trace_id: str,
        workspace_id: str,
        base_domain_id: int,
        base_domain_name: str,
        prompt: str,
        capabilities: Mapping[str, Any],
        conversation_context: Optional[PlanConversationContext],
        semester_indicator_columns: Mapping[str, Any],
        domain_time_policy: Mapping[str, Any],
        schema: Dict[str, Any],
        fast_mode: bool,
        profile_steps: List[Dict[str, Any]],
        profile_enabled: bool,
        pipeline_trace: Dict[str, Any],
        trace_capture_enabled: bool,
    ) -> PlanPostprocessResult:
        timings: Dict[str, int] = {}
        validated, semantic_alias_debug, norm_debug, validation_timings = self._normalize_and_validate(
            llm_result=llm_result,
            trace_id=trace_id,
            workspace_id=workspace_id,
            base_domain_id=base_domain_id,
            base_domain_name=base_domain_name,
            prompt=prompt,
            capabilities=capabilities,
            conversation_context=conversation_context,
            semester_indicator_columns=semester_indicator_columns,
            domain_time_policy=domain_time_policy,
            profile_steps=profile_steps,
            profile_enabled=profile_enabled,
            pipeline_trace=pipeline_trace,
            trace_capture_enabled=trace_capture_enabled,
            step_name="plan_normalization",
            step_label="Normalize plan and apply deterministic value/filter normalizers",
        )
        for row in validation_timings:
            timings[str(row.get("timing_key") or "")] = int(row.get("ms") or 0)

        district_county_retry_hint = _district_county_retry_hint(
            normalized_prompt=prompt,
            plan_json=validated.plan_json,
            capabilities=capabilities,
        )
        retry_needed = (
            (not validated.is_valid and (_should_retry_after_validation(validated.issues) or fast_mode))
            or (not fast_mode and bool(district_county_retry_hint))
        )
        if retry_needed:
            t_llm_retry = perf_counter()
            retry_feedback = _format_validation_feedback(validated.issues)
            llm_retry = self._llm_planning._call_llm_plan(
                normalized_prompt=prompt,
                workspace_id=workspace_id,
                base_domain_id=base_domain_id,
                capabilities=capabilities_llm,
                schema=schema,
                slot_hints=slot_hints,
                validation_feedback=retry_feedback,
                retry_hint=district_county_retry_hint or "",
                conversation_context=conversation_context,
                fast_mode=fast_mode,
            )
            timings["llm_retry"] = _add_pipeline_step(
                profile_steps=profile_steps,
                enabled=profile_enabled,
                step="llm_retry",
                label="Retry PlanV2 generation after validation feedback",
                started_at=t_llm_retry,
            )
            _append_pipeline_trace_step(
                trace=pipeline_trace,
                enabled=trace_capture_enabled,
                step="llm_retry",
                data={
                    "validation_feedback": retry_feedback,
                    "llm_raw_json": llm_retry.raw_content,
                    "llm_attempts": llm_retry.attempts,
                    "llm_repaired": llm_retry.repaired,
                },
            )
            validated, semantic_alias_debug, norm_debug, validation_timings = self._normalize_and_validate(
                llm_result=llm_retry,
                trace_id=trace_id,
                workspace_id=workspace_id,
                base_domain_id=base_domain_id,
                base_domain_name=base_domain_name,
                prompt=prompt,
                capabilities=capabilities,
                conversation_context=conversation_context,
                semester_indicator_columns=semester_indicator_columns,
                domain_time_policy=domain_time_policy,
                profile_steps=profile_steps,
                profile_enabled=profile_enabled,
                pipeline_trace=pipeline_trace,
                trace_capture_enabled=trace_capture_enabled,
                step_name="retry_plan_normalization",
                step_label="Normalize retry plan and re-apply deterministic normalizers",
            )
            for row in validation_timings:
                timings[str(row.get("timing_key") or "")] = int(row.get("ms") or 0)
            llm_result = llm_retry

        return PlanPostprocessResult(
            validated=validated,
            llm_result=llm_result,
            semantic_alias_debug=semantic_alias_debug,
            country_debug=list(norm_debug.get("country") or []),
            school_year_debug=list(norm_debug.get("school_year") or []),
            semester_debug=list(norm_debug.get("semester") or []),
            school_name_debug=list(norm_debug.get("school_name") or []),
            staff_role_debug=list(norm_debug.get("staff_role") or []),
            adm_default_debug=list(norm_debug.get("adm_default") or []),
            district_county_retry_hint=district_county_retry_hint or None,
            timings=timings,
        )
