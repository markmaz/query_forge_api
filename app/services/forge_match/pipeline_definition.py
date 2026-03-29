from __future__ import annotations

from app.services.shared_ai.adapters.capabilities import CandidateCapabilityAdapter, HeuristicColumnCapabilityAdapter
from app.services.shared_ai.adapters.policies import CandidatePolicyRerankAdapter, PlannerPolicyRerankAdapter
from app.services.shared_ai.graph import PipelineDefinition, PipelineEdge
from app.services.shared_ai.nodes.apply_policy_rerank import ApplyPolicyRerankNode
from app.services.shared_ai.nodes.extract_signals import ExtractSignalsNode
from app.services.shared_ai.nodes.normalize_text import NormalizeTextNode
from app.services.shared_ai.nodes.resolve_capabilities import ResolveCapabilitiesNode
from app.services.shared_ai.nodes.retrieve_candidates import CandidateRetrievalAdapter, RetrieveCandidatesNode


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
    rerank = ApplyPolicyRerankNode(adapter=policy_adapter or PlannerPolicyRerankAdapter())

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


__all__ = ["build_forge_match_candidate_pipeline_definition"]
