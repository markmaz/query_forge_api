"""Domain selection orchestration extracted from PlannerDomainService."""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from app.infra.embedding_model import EmbeddingModel
from app.infra.qdrant_client import QdrantClientWrapper
from app.services.domain.planner_capability_packing_policy_service import PlannerCapabilityPackingPolicyService
from app.services.domain.planner_domain_selection_policy_service import PlannerDomainSelectionPolicyService
from app.services.domain.planner_projection_policy_service import PlannerProjectionPolicyService
from app.services.domain.planner_retrieval_policy_service import PlannerRetrievalPolicyService
from app.services.domains.capabilities_service import DomainCapabilitiesService
from app.services.planner_domain.capability_compactor import (
    _collect_domain_selection_capability_features,
    _collect_domain_selection_shortlist_features,
    compact_capabilities_for_llm as build_compact_capabilities_for_llm,
    full_capabilities_for_execution as build_full_capabilities_for_execution,
)
from app.services.planner_domain.column_shortlister import (
    shortlist_columns_for_domain as build_shortlisted_columns_for_domain,
)
from app.services.planner_domain.domain_candidate_retriever import (
    get_domain_candidates as load_domain_candidates,
)
from app.services.planner_domain.domain_selection_ranking import (
    select_domain_and_shortlist_columns as choose_domain_and_shortlist_columns,
)
from app.services.planner_domain.prompt_signal_service import PromptSignalService
from app.services.planner_domain.prompt_intents import _extract_time_phrases
from app.services.planner_domain.rerank_policy_engine import PlannerDomainRerankPolicyEngine
from app.services.planner_domain.pipeline_definition import build_planner_domain_selection_pipeline_definition
from app.services.planner.semantic_grounding_service import SemanticGroundingService
from app.services.shared_ai.context import PipelineContext
from app.services.shared_ai.executor import PipelineExecutor


# ---------------------------------------------------------------------------
# DomainSelectionService
# ---------------------------------------------------------------------------


class DomainSelectionService:
    """Encapsulates domain candidate retrieval, scoring, and column shortlisting."""

    def __init__(
        self,
        *,
        domain_vector: Any,
        capabilities_service: DomainCapabilitiesService,
        rerank_policy_engine: PlannerDomainRerankPolicyEngine,
        embedding_model_factory: Callable[[], EmbeddingModel],
        column_vector_factory: Callable[[], QdrantClientWrapper],
        semantic_grounding_factory: Callable[[], SemanticGroundingService],
        semantic_alias_constraints_fn: Callable[..., List[Dict[str, Any]]],
        projection_policy_service: Optional[PlannerProjectionPolicyService] = None,
        retrieval_policy_service: Optional[PlannerRetrievalPolicyService] = None,
        domain_selection_policy_service: Optional[PlannerDomainSelectionPolicyService] = None,
    ) -> None:
        from app.services.shared_ai.adapters.capabilities import DomainCapabilityResolverAdapter
        from app.services.shared_ai.adapters.policies import PolicyDrivenRerankAdapter

        self._domain_vector = domain_vector
        self._capabilities = capabilities_service
        self._rerank_policy_engine = rerank_policy_engine
        self._pipeline_executor = PipelineExecutor()
        self._planner_capability_adapter = DomainCapabilityResolverAdapter(
            resolver=rerank_policy_engine.capability_service,
        )
        self._planner_policy_adapter = PolicyDrivenRerankAdapter(
            policy_provider=rerank_policy_engine.policy_service,
        )
        self._embedding_model_factory = embedding_model_factory
        self._column_vector_factory = column_vector_factory
        self._semantic_grounding_factory = semantic_grounding_factory
        self._semantic_alias_constraints_fn = semantic_alias_constraints_fn
        self._projection_policy_service = projection_policy_service or PlannerProjectionPolicyService()
        self._retrieval_policy_service = retrieval_policy_service or PlannerRetrievalPolicyService()
        self._domain_selection_policy_service = domain_selection_policy_service or PlannerDomainSelectionPolicyService()
        self._last_pipeline_context: Optional[PipelineContext] = None

    def select_domain_and_shortlist(
        self,
        *,
        workspace_id: str,
        user_id: str,
        prompt: str,
        provided_domain_id: Optional[int],
    ) -> Tuple[List[Dict[str, Any]], int, Dict[str, Any], List[Dict[str, Any]], List[Dict[str, Any]], List[str]]:
        """Public entry point combining candidate retrieval and domain selection.

        Returns a 6-tuple:
            (domain_candidates, selected_domain_id, capabilities,
             shortlisted_columns, ranking_debug, rerank_signals)
        """
        self._last_pipeline_context = None
        domain_candidates = self._get_domain_candidates(
            workspace_id=workspace_id,
            prompt=prompt,
            provided_domain_id=provided_domain_id,
        )
        selected_domain_id, capabilities, shortlisted_columns, ranking_debug, rerank_signals = (
            self._select_domain_and_shortlist_columns(
                workspace_id=workspace_id,
                user_id=user_id,
                prompt=prompt,
                domain_candidates=domain_candidates,
            )
        )
        return (
            domain_candidates,
            selected_domain_id,
            capabilities,
            shortlisted_columns,
            ranking_debug,
            rerank_signals,
        )

    @staticmethod
    def compact_capabilities_for_llm(
        capabilities: Mapping[str, Any],
        shortlisted_columns: Sequence[Mapping[str, Any]],
        prompt: str,
        slot_hints: Optional[Mapping[str, Any]] = None,
        fast_mode: bool = False,
        workspace_id: Optional[str] = None,
        projection_policy_service: Optional[PlannerProjectionPolicyService] = None,
        capability_packing_policy_service: Optional[PlannerCapabilityPackingPolicyService] = None,
        include_projection_policy_debug: bool = False,
    ) -> Dict[str, Any]:
        return build_compact_capabilities_for_llm(
            capabilities=capabilities,
            shortlisted_columns=shortlisted_columns,
            prompt=prompt,
            slot_hints=slot_hints,
            fast_mode=fast_mode,
            workspace_id=workspace_id,
            projection_policy_service=projection_policy_service,
            capability_packing_policy_service=capability_packing_policy_service,
            include_projection_policy_debug=include_projection_policy_debug,
        )

    @staticmethod
    def full_capabilities_for_execution(capabilities: Mapping[str, Any]) -> Dict[str, Any]:
        return build_full_capabilities_for_execution(capabilities)

    @staticmethod
    def _score_domain_candidate(
        prompt: str,
        candidate: Mapping[str, Any],
        capabilities: Mapping[str, Any],
        shortlisted_columns: Sequence[Mapping[str, Any]],
        selection_policy_service: Optional[PlannerDomainSelectionPolicyService] = None,
    ) -> float:
        vector_score = max(0.0, float(candidate.get("score") or 0.0))
        dimension_count = max(1, len(list(capabilities.get("dimensions") or [])))
        shortlist_ratio = min(1.0, len(list(shortlisted_columns)) / float(min(70, dimension_count)))
        score = (vector_score * 0.65) + (shortlist_ratio * 0.35)
        score += (selection_policy_service or PlannerDomainSelectionPolicyService()).score_adjustment(
            workspace_id=None,
            prompt_signals=PromptSignalService().extract_signals(prompt=prompt),
            shortlist_features=_collect_domain_selection_shortlist_features(shortlisted_columns=shortlisted_columns),
            capability_features=_collect_domain_selection_capability_features(capabilities=capabilities),
        )
        score += PlannerRetrievalPolicyService(enable_db_lookup=False).score_domain_name_bias(
            workspace_id=None,
            prompt_signals=PromptSignalService().extract_signals(prompt=prompt),
            candidate_name=str(candidate.get("name") or ""),
        )
        if len(shortlisted_columns) < 5:
            score -= 0.1
        return round(score, 5)

    @staticmethod
    def _score_semantic_grounding_bundle(
        prompt: str,
        grounding_bundle: Any,
    ) -> float:
        candidates = getattr(grounding_bundle, "candidates", None)
        alias_constraints = list(getattr(grounding_bundle, "alias_constraints", []) or [])
        if candidates is None:
            return 0.02 if alias_constraints else 0.0

        score = 0.0
        metric_count = len(list(getattr(candidates, "metric_candidates", []) or []))
        dimension_count = len(list(getattr(candidates, "dimension_candidates", []) or []))
        filter_count = len(list(getattr(candidates, "filter_candidates", []) or []))
        time_count = len(list(getattr(candidates, "time_candidates", []) or []))

        if metric_count > 0:
            score += 0.06
        if dimension_count > 0:
            score += 0.05
        if filter_count > 0:
            score += 0.04
        if time_count > 0 and _extract_time_phrases(prompt):
            score += 0.03
        if alias_constraints:
            score += min(0.04, 0.02 * len(alias_constraints))

        metadata = dict(getattr(candidates, "metadata", {}) or {})
        if metadata.get("semantic_source") not in {None, "", "fallback_capabilities"}:
            score += 0.02

        return round(min(0.22, score), 5)

    def _get_domain_candidates(
        self,
        *,
        workspace_id: str,
        prompt: str,
        provided_domain_id: Optional[int],
    ) -> List[Dict[str, Any]]:
        return load_domain_candidates(
            workspace_id=workspace_id,
            prompt=prompt,
            provided_domain_id=provided_domain_id,
            search_domains_fn=self._domain_vector.search_domains,
            semantic_alias_constraints_fn=self._semantic_alias_constraints_fn,
            extract_prompt_signals_fn=self._rerank_policy_engine.extract_prompt_signals,
            retrieval_policy_service=self._retrieval_policy_service,
        )

    def _select_domain_and_shortlist_columns(
        self,
        *,
        workspace_id: str,
        user_id: str,
        prompt: str,
        domain_candidates: Sequence[Mapping[str, Any]],
    ) -> Tuple[int, Dict[str, Any], List[Dict[str, Any]], List[Dict[str, Any]], List[str]]:
        (
            pipeline_context,
            selected_domain_id,
            capabilities,
            shortlisted_columns,
            ranking,
            rerank_signals,
        ) = choose_domain_and_shortlist_columns(
            workspace_id=workspace_id,
            user_id=user_id,
            prompt=prompt,
            domain_candidates=domain_candidates,
            get_domain_capabilities_fn=self._capabilities.get_domain_capabilities,
            shortlist_columns_fn=lambda **kwargs: self._shortlist_columns_for_domain(**kwargs),
            compact_capabilities_fn=self.compact_capabilities_for_llm,
            semantic_grounding_factory=self._semantic_grounding_factory,
            score_semantic_grounding_bundle_fn=self._score_semantic_grounding_bundle,
            score_domain_candidate_fn=lambda **kwargs: self._score_domain_candidate(**kwargs),
            domain_selection_policy_service=self._domain_selection_policy_service,
            projection_policy_service=self._projection_policy_service,
            planner_capability_adapter=self._planner_capability_adapter,
            planner_policy_adapter=self._planner_policy_adapter,
            pipeline_executor=self._pipeline_executor,
            pipeline_definition_factory=build_planner_domain_selection_pipeline_definition,
        )
        self._last_pipeline_context = pipeline_context
        return (
            selected_domain_id,
            capabilities,
            shortlisted_columns,
            ranking,
            rerank_signals,
        )

    @property
    def last_pipeline_context(self) -> Optional[PipelineContext]:
        return self._last_pipeline_context

    def _shortlist_columns_for_domain(
        self,
        *,
        prompt: str,
        workspace_id: str,
        capabilities: Mapping[str, Any],
    ) -> List[Dict[str, Any]]:
        return build_shortlisted_columns_for_domain(
            prompt=prompt,
            workspace_id=workspace_id,
            capabilities=capabilities,
            embedding_model_factory=self._embedding_model_factory,
            column_vector_factory=self._column_vector_factory,
        )
