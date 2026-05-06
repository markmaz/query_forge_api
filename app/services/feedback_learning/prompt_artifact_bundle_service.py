from __future__ import annotations

from typing import Any, Dict, Mapping, Optional

from app.exceptions.forge_error import ForgeError
from app.repositories.feedback_learning import PromptFeedbackRepository
from app.schemas.feedback_learning import PromptArtifactBundle
from app.services.planner_domain.conversation_store import HybridPlannerDomainConversationStore
from app.services.planner_domain.pipeline_trace import PipelineTraceService


class PromptArtifactBundleService:
    def __init__(
        self,
        *,
        prompt_feedback_repository: Optional[PromptFeedbackRepository] = None,
        pipeline_trace_service: Optional[PipelineTraceService] = None,
        conversation_store: Optional[HybridPlannerDomainConversationStore] = None,
    ) -> None:
        self._prompt_feedback_repository = prompt_feedback_repository or PromptFeedbackRepository()
        self._pipeline_trace_service = pipeline_trace_service or PipelineTraceService()
        self._conversation_store = conversation_store or HybridPlannerDomainConversationStore()

    def build_bundle(self, prompt_feedback_id: int) -> PromptArtifactBundle:
        feedback = self._prompt_feedback_repository.get_feedback(prompt_feedback_id=int(prompt_feedback_id))
        if feedback is None:
            raise ForgeError("Prompt feedback not found", status_code=404, details={"prompt_feedback_id": int(prompt_feedback_id)})

        response_json = dict(feedback.get("response_json") or {}) if isinstance(feedback.get("response_json"), Mapping) else {}
        meta_json = dict(feedback.get("meta_json") or {}) if isinstance(feedback.get("meta_json"), Mapping) else {}
        workspace_id = str(feedback.get("workspace_id") or "").strip()
        user_id = str(feedback.get("user_id") or "").strip()
        trace_id = _first_text(
            feedback.get("trace_id"),
            response_json.get("trace_id"),
            response_json.get("traceId"),
            _nested_get(response_json, "technical_details", "trace_id"),
        )
        pipeline_profile = self._load_pipeline_profile(trace_id=trace_id, workspace_id=workspace_id, user_id=user_id)
        pipeline_trace = dict(pipeline_profile.get("pipeline_trace") or {}) if isinstance(pipeline_profile.get("pipeline_trace"), Mapping) else {}

        conversation_id = _first_text(
            response_json.get("conversation_id"),
            response_json.get("conversationId"),
            _nested_get(response_json, "technical_details", "conversation_id"),
            meta_json.get("conversation_id"),
            pipeline_profile.get("conversation_id"),
        )
        conversation_state = self._load_conversation_state(
            workspace_id=workspace_id,
            user_id=user_id,
            conversation_id=conversation_id,
        )

        prompt = _first_text(
            feedback.get("prompt_text"),
            pipeline_profile.get("prompt"),
            conversation_state.get("last_prompt"),
        )
        normalized_prompt = _first_text(
            feedback.get("normalized_prompt"),
            response_json.get("normalized_prompt"),
            _nested_get(response_json, "plan_json_v2", "normalized_prompt"),
            _nested_get(response_json, "sql_json", "meta", "normalized_prompt"),
            pipeline_trace.get("normalized_prompt"),
            prompt,
        )
        planner_output = _first_mapping(
            response_json,
            _nested_get(pipeline_trace, "response"),
        )
        generated_sql = _first_mapping(
            response_json.get("sql_json"),
            conversation_state.get("sql_json"),
            _pipeline_step_data(pipeline_trace, step="map_to_sqljson", key="sql_json"),
        )
        planner_plan = _first_mapping(
            response_json.get("plan_json_v2"),
            conversation_state.get("plan_json_v2"),
        )

        planner_input = {
            "workspace_id": workspace_id,
            "user_id": user_id,
            "trace_id": trace_id,
            "conversation_id": conversation_id,
            "prompt": prompt,
            "normalized_prompt": normalized_prompt,
            "meta": meta_json,
            "trace_context": {
                "profile_prompt": pipeline_profile.get("prompt"),
                "profile_steps": list(pipeline_profile.get("steps") or []),
            },
        }
        if planner_plan:
            planner_input["plan_json_v2"] = planner_plan

        output_json = response_json
        candidate_domains = _first_list_of_mappings(
            _nested_get(response_json, "debug", "domain_candidates"),
            _pipeline_step_data(pipeline_trace, step="domain_selection", key="domain_candidates"),
        )
        candidate_concepts = _first_list(
            _nested_get(response_json, "debug", "semantic_grounding", "candidate_concepts"),
            _nested_get(response_json, "debug", "semantic_grounding", "candidates"),
        )
        selected_concepts = _first_list(
            _nested_get(response_json, "debug", "semantic_grounding", "selected_concepts"),
            _nested_get(response_json, "plan_json_v2", "selected_concepts"),
        )
        result_preview = _first_non_none(
            response_json.get("explanation"),
            response_json.get("result_preview"),
        )

        missing_fields = []
        if not prompt:
            missing_fields.append("prompt")
        if not normalized_prompt:
            missing_fields.append("normalized_prompt")
        if not planner_output:
            missing_fields.append("planner_output")
        if not generated_sql:
            missing_fields.append("generated_sql")
        if not output_json:
            missing_fields.append("output_json")
        if missing_fields:
            raise ForgeError(
                "Missing required prompt feedback artifacts",
                status_code=422,
                details={
                    "prompt_feedback_id": int(prompt_feedback_id),
                    "missing_fields": missing_fields,
                    "trace_id": trace_id,
                    "conversation_id": conversation_id,
                },
            )

        try:
            return PromptArtifactBundle.model_validate(
                {
                    "prompt_feedback_id": int(prompt_feedback_id),
                    "workspace_id": workspace_id,
                    "user_id": user_id,
                    "trace_id": trace_id,
                    "conversation_id": conversation_id,
                    "prompt": prompt,
                    "normalized_prompt": normalized_prompt,
                    "planner_input": planner_input,
                    "planner_output": planner_output,
                    "generated_sql": generated_sql,
                    "output_json": output_json,
                    "candidate_domains": candidate_domains,
                    "candidate_concepts": candidate_concepts,
                    "selected_concepts": selected_concepts,
                    "result_preview": result_preview,
                }
            )
        except Exception as exc:  # pragma: no cover - pydantic failure path exercised via validation tests
            raise ForgeError(
                "Invalid prompt artifact bundle",
                status_code=500,
                details={"prompt_feedback_id": int(prompt_feedback_id), "error": str(exc)},
            ) from exc

    def _load_pipeline_profile(self, *, trace_id: Optional[str], workspace_id: str, user_id: str) -> Dict[str, Any]:
        if not trace_id:
            return {}
        try:
            profile = self._pipeline_trace_service.get_pipeline_profile(
                trace_id=trace_id,
                workspace_id=workspace_id,
                user_id=user_id,
            )
        except ForgeError as exc:
            if int(exc.status_code or 500) == 404:
                return {}
            raise
        return dict(profile or {}) if isinstance(profile, Mapping) else {}

    def _load_conversation_state(
        self,
        *,
        workspace_id: str,
        user_id: str,
        conversation_id: Optional[str],
    ) -> Dict[str, Any]:
        if not conversation_id:
            return {}
        state = self._conversation_store.get_state(
            workspace_id=workspace_id,
            user_id=user_id,
            conversation_id=conversation_id,
        )
        return dict(state or {}) if isinstance(state, Mapping) else {}


def _nested_get(value: Any, *path: str) -> Any:
    current = value
    for key in path:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    return current


def _first_non_none(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


def _first_text(*values: Any) -> Optional[str]:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def _first_mapping(*values: Any) -> Dict[str, Any]:
    for value in values:
        if isinstance(value, Mapping) and value:
            return dict(value)
    return {}


def _first_list(*values: Any) -> Optional[list[Any]]:
    for value in values:
        if isinstance(value, list) and value:
            return list(value)
    return None


def _first_list_of_mappings(*values: Any) -> Optional[list[Dict[str, Any]]]:
    for value in values:
        if not isinstance(value, list) or not value:
            continue
        out = [dict(item) for item in value if isinstance(item, Mapping)]
        if out:
            return out
    return None


def _pipeline_step_data(pipeline_trace: Mapping[str, Any], *, step: str, key: str) -> Any:
    steps = pipeline_trace.get("steps")
    if not isinstance(steps, list):
        return None
    for item in steps:
        if not isinstance(item, Mapping):
            continue
        if str(item.get("step") or "").strip() != step:
            continue
        data = item.get("data")
        if not isinstance(data, Mapping):
            continue
        return data.get(key)
    return None


__all__ = ["PromptArtifactBundleService"]
