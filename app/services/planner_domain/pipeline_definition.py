from __future__ import annotations

from typing import Any

from app.services.shared_ai.graph import PipelineDefinition, PipelineEdge
from app.services.shared_ai.nodes.apply_policy_rerank import ApplyPolicyRerankNode
from app.services.shared_ai.nodes.extract_signals import ExtractSignalsNode
from app.services.shared_ai.nodes.normalize_text import NormalizeTextNode
from app.services.shared_ai.nodes.resolve_capabilities import ResolveCapabilitiesNode


def build_planner_domain_selection_pipeline_definition(
    *,
    capability_adapter: Any,
    policy_adapter: Any,
) -> PipelineDefinition:
    normalize = NormalizeTextNode()
    extract = ExtractSignalsNode()
    resolve = ResolveCapabilitiesNode(adapter=capability_adapter)
    rerank = ApplyPolicyRerankNode(adapter=policy_adapter)

    return PipelineDefinition(
        name="planner_domain_selection_pipeline",
        nodes={
            normalize.name: normalize,
            extract.name: extract,
            resolve.name: resolve,
            rerank.name: rerank,
        },
        edges=[
            PipelineEdge(from_node=normalize.name, to_node=extract.name),
            PipelineEdge(from_node=extract.name, to_node=rerank.name),
            PipelineEdge(from_node=resolve.name, to_node=rerank.name),
        ],
        start_nodes=[normalize.name, resolve.name],
    )


__all__ = ["build_planner_domain_selection_pipeline_definition"]
