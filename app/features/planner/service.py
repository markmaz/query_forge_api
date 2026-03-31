from __future__ import annotations

class PlannerFeatureService:
    def __init__(
        self,
        *,
        semantic_extract_service_factory=None,
        planner_domain_service_factory=None,
        planner_llm_service_factory=None,
        planner_llm_enabled: bool = True,
    ) -> None:
        self._semantic_extract_service_factory = semantic_extract_service_factory
        self._planner_domain_service_factory = planner_domain_service_factory
        self._planner_llm_service_factory = planner_llm_service_factory
        self._planner_llm_enabled = planner_llm_enabled

    def _semantic_extract_factory(self):
        if self._semantic_extract_service_factory is not None:
            return self._semantic_extract_service_factory
        from app.services.planner.semantic_extract_service import SemanticExtractService

        return SemanticExtractService

    def _planner_domain_factory(self):
        if self._planner_domain_service_factory is not None:
            return self._planner_domain_service_factory
        from app.services.planner_domain import PlannerDomainService

        return PlannerDomainService

    def _planner_llm_factory(self):
        if self._planner_llm_service_factory is not None:
            return self._planner_llm_service_factory
        from app.services.planner_llm import PlannerLLMService

        return PlannerLLMService

    @property
    def planner_llm_enabled(self) -> bool:
        return self._planner_llm_enabled

    def extract(self, prompt: str):
        return self._semantic_extract_factory()().extract(prompt)

    def plan_domain(self, body: dict, *, user_id: str):
        return self._planner_domain_factory()().plan(body, user_id=user_id)

    def emit_failed_plan_trace(self, *, payload: dict, user_id: str, error: Exception):
        return self._planner_domain_factory()().emit_failed_plan_trace(
            payload=payload,
            user_id=user_id,
            error=error,
        )

    def get_pipeline_profile(self, *, trace_id: str, workspace_id: str, user_id: str):
        return self._planner_domain_factory()().get_pipeline_profile(
            trace_id=trace_id,
            workspace_id=workspace_id,
            user_id=user_id,
        )

    def generate_next_actions(self, body: dict, *, user_id: str):
        return self._planner_domain_factory()().generate_next_actions(body, user_id=user_id)

    def plan_llm(self, body: dict):
        return self._planner_llm_factory()().plan(body)
