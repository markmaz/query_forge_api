from __future__ import annotations

import json
from typing import Any, Dict, Mapping

from app.schemas.feedback_learning import EvaluatorAnalysis, PromptArtifactBundle


class EvaluatorPromptBuilder:
    def build_prompts(self, *, bundle: PromptArtifactBundle) -> Dict[str, str]:
        schema_json = json.dumps(EvaluatorAnalysis.model_json_schema(), ensure_ascii=True, sort_keys=True)
        system_prompt = (
            "You are QueryForge's governed feedback-learning evaluator.\n"
            "Analyze a single negative prompt-feedback event and decide whether it indicates planner error, domain error, ambiguity, "
            "inconclusive evidence, or no action.\n"
            "Return JSON only that conforms exactly to this schema:\n"
            f"{schema_json}\n"
            "Do not guess. If the evidence is insufficient, return verdict='inconclusive' with no speculative proposed changes."
        )

        user_payload: Dict[str, Any] = {
            "prompt": bundle.prompt,
            "normalized_prompt": bundle.normalized_prompt,
            "planner_input": self._summarize_planner_input(bundle.planner_input),
            "planner_output_summary": self._summarize_planner_output(bundle.planner_output),
            "generated_sql": bundle.generated_sql,
            "output_summary": self._summarize_output_json(bundle.output_json),
        }
        if bundle.candidate_domains is not None:
            user_payload["candidate_domains"] = bundle.candidate_domains
        if bundle.candidate_concepts is not None:
            user_payload["candidate_concepts"] = bundle.candidate_concepts
        if bundle.selected_concepts is not None:
            user_payload["selected_concepts"] = bundle.selected_concepts
        if bundle.result_preview is not None:
            user_payload["result_preview"] = bundle.result_preview

        return {
            "system_prompt": system_prompt,
            "user_prompt": json.dumps(user_payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")),
        }

    def _summarize_planner_input(self, planner_input: Mapping[str, Any]) -> Dict[str, Any]:
        return {
            "workspace_id": planner_input.get("workspace_id"),
            "trace_id": planner_input.get("trace_id"),
            "conversation_id": planner_input.get("conversation_id"),
            "prompt": planner_input.get("prompt"),
            "normalized_prompt": planner_input.get("normalized_prompt"),
            "meta": dict(planner_input.get("meta") or {}) if isinstance(planner_input.get("meta"), Mapping) else {},
        }

    def _summarize_planner_output(self, planner_output: Mapping[str, Any]) -> Dict[str, Any]:
        plan_json = planner_output.get("plan_json_v2")
        validation = planner_output.get("validation")
        explanation = planner_output.get("explanation")
        next_actions = planner_output.get("next_actions")
        debug = planner_output.get("debug")

        summary: Dict[str, Any] = {
            "trace_id": planner_output.get("trace_id"),
            "conversation_id": planner_output.get("conversation_id"),
            "has_plan_json_v2": isinstance(plan_json, Mapping),
            "validation": dict(validation) if isinstance(validation, Mapping) else {},
            "explanation": dict(explanation) if isinstance(explanation, Mapping) else {},
            "next_actions_count": len(next_actions) if isinstance(next_actions, list) else 0,
        }
        if isinstance(plan_json, Mapping):
            summary["plan_json_v2"] = {
                "base_domain_id": plan_json.get("base_domain_id"),
                "intent": plan_json.get("intent"),
                "entity_scope": plan_json.get("entity_scope"),
                "metrics": list(plan_json.get("metrics") or []) if isinstance(plan_json.get("metrics"), list) else [],
                "filters": list(plan_json.get("filters") or []) if isinstance(plan_json.get("filters"), list) else [],
            }
        if isinstance(debug, Mapping):
            summary["debug_summary"] = {
                "selected_domain_id": debug.get("selected_domain_id"),
                "column_shortlist_count": debug.get("column_shortlist_count"),
                "semantic_assist_enabled": debug.get("semantic_assist_enabled"),
            }
        return summary

    def _summarize_output_json(self, output_json: Mapping[str, Any]) -> Dict[str, Any]:
        return {
            "trace_id": output_json.get("trace_id"),
            "conversation_id": output_json.get("conversation_id"),
            "next_actions_status": output_json.get("next_actions_status"),
            "has_debug": isinstance(output_json.get("debug"), Mapping),
            "has_explanation": isinstance(output_json.get("explanation"), Mapping),
            "timings_ms": dict(output_json.get("timings_ms") or {}) if isinstance(output_json.get("timings_ms"), Mapping) else {},
        }


__all__ = ["EvaluatorPromptBuilder"]
