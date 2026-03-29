from __future__ import annotations

from typing import Any, Callable

from app.services.shared_ai.adapters.capabilities import CandidateCapabilityAdapter, HeuristicColumnCapabilityAdapter
from app.services.shared_ai.adapters.policies import CandidatePolicyRerankAdapter, PolicyDrivenRerankAdapter
from app.services.shared_ai.graph import PipelineDefinition, PipelineEdge
from app.services.shared_ai.nodes.apply_policy_rerank import ApplyPolicyRerankNode
from app.services.shared_ai.nodes.dispatch_subgraph import DispatchSubgraphNode
from app.services.shared_ai.nodes.extract_signals import ExtractSignalsNode
from app.services.shared_ai.nodes.normalize_text import NormalizeTextNode
from app.services.shared_ai.nodes.rank_candidates import RankCandidatesNode
from app.services.shared_ai.nodes.resolve_capabilities import ResolveCapabilitiesNode
from app.services.shared_ai.nodes.retrieve_candidates import CandidateRetrievalAdapter, RetrieveCandidatesNode
from app.services.shared_ai.nodes.score_confidence import ScoreConfidenceNode


def build_forge_match_candidate_pipeline_definition(
    *,
    retrieval_adapter: CandidateRetrievalAdapter,
    capability_adapter: CandidateCapabilityAdapter | None = None,
    policy_adapter: CandidatePolicyRerankAdapter | None = None,
) -> PipelineDefinition:
    normalize = NormalizeTextNode()
    extract = ExtractSignalsNode()
    retrieve = RetrieveCandidatesNode(adapter=retrieval_adapter)
    resolve = ResolveCapabilitiesNode(adapter=capability_adapter or HeuristicColumnCapabilityAdapter())
    rerank = ApplyPolicyRerankNode(adapter=policy_adapter or PolicyDrivenRerankAdapter())

    return PipelineDefinition(
        name="forge_match_candidate_pipeline",
        nodes={
            normalize.name: normalize,
            extract.name: extract,
            retrieve.name: retrieve,
            resolve.name: resolve,
            rerank.name: rerank,
        },
        edges=[
            PipelineEdge(from_node=normalize.name, to_node=extract.name),
            PipelineEdge(from_node=retrieve.name, to_node=resolve.name),
            PipelineEdge(from_node=extract.name, to_node=rerank.name),
            PipelineEdge(from_node=resolve.name, to_node=rerank.name),
        ],
        start_nodes=[normalize.name, retrieve.name],
    )


def build_forge_match_row_pipeline_definition(
    *,
    candidate_pipeline_factory: Callable[[Any], PipelineDefinition],
    ranking_adapter: Any,
    confidence_adapter: Any,
) -> PipelineDefinition:
    dispatch = DispatchSubgraphNode(
        definition_factory=candidate_pipeline_factory,
        name="dispatch_candidate_pipeline",
        produces=("prompt_signals", "capability_map", "reranked_candidates"),
    )
    rank = RankCandidatesNode(adapter=ranking_adapter)
    confidence = ScoreConfidenceNode(adapter=confidence_adapter)

    return PipelineDefinition(
        name="forge_match_row_pipeline",
        nodes={
            dispatch.name: dispatch,
            rank.name: rank,
            confidence.name: confidence,
        },
        edges=[
            PipelineEdge(from_node=dispatch.name, to_node=rank.name),
            PipelineEdge(from_node=rank.name, to_node=confidence.name),
        ],
        start_nodes=[dispatch.name],
    )


__all__ = [
    "build_forge_match_candidate_pipeline_definition",
    "build_forge_match_row_pipeline_definition",
]
