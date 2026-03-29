from __future__ import annotations

from app.services.forge_match.pipeline_definition import build_forge_match_candidate_pipeline_definition
from app.services.planner_domain.pipeline_definition import build_planner_domain_selection_pipeline_definition
from app.services.shared_ai.artifacts import CandidateSetArtifact, RerankedCandidatesArtifact
from app.services.shared_ai.context import PipelineContext
from app.services.shared_ai.graph import validate_pipeline_definition


class _RetrievalAdapter:
    def retrieve(self, *, context: PipelineContext) -> CandidateSetArtifact:
        del context
        return CandidateSetArtifact()


class _CapabilityAdapter:
    def resolve(self, *, context: PipelineContext, candidates):
        del context
        return list(candidates), type("CapabilityMapArtifactLike", (), {"candidate_capabilities": {}, "capability_records": {}, "debug": {}})()


class _PolicyAdapter:
    def rerank(self, *, context: PipelineContext, candidates, prompt_signals, capability_map):
        del context, candidates, prompt_signals, capability_map
        return RerankedCandidatesArtifact()


def test_forge_match_pipeline_definition_declares_expected_nodes_and_edges() -> None:
    definition = build_forge_match_candidate_pipeline_definition(
        retrieval_adapter=_RetrievalAdapter(),
        capability_adapter=_CapabilityAdapter(),
        policy_adapter=_PolicyAdapter(),
    )

    validate_pipeline_definition(definition)

    assert definition.name == "forge_match_candidate_pipeline"
    assert definition.start_nodes == ["normalize_text", "retrieve_candidates"]
    assert sorted(definition.nodes.keys()) == [
        "apply_policy_rerank",
        "extract_signals",
        "normalize_text",
        "resolve_capabilities",
        "retrieve_candidates",
    ]
    assert {(edge.from_node, edge.to_node) for edge in definition.edges} == {
        ("normalize_text", "extract_signals"),
        ("retrieve_candidates", "resolve_capabilities"),
        ("extract_signals", "apply_policy_rerank"),
        ("resolve_capabilities", "apply_policy_rerank"),
    }


def test_planner_domain_pipeline_definition_declares_expected_nodes_and_edges() -> None:
    definition = build_planner_domain_selection_pipeline_definition(
        capability_adapter=_CapabilityAdapter(),
        policy_adapter=_PolicyAdapter(),
    )

    validate_pipeline_definition(definition)

    assert definition.name == "planner_domain_selection_pipeline"
    assert definition.start_nodes == ["normalize_text", "resolve_capabilities"]
    assert sorted(definition.nodes.keys()) == [
        "apply_policy_rerank",
        "extract_signals",
        "normalize_text",
        "resolve_capabilities",
    ]
    assert {(edge.from_node, edge.to_node) for edge in definition.edges} == {
        ("normalize_text", "extract_signals"),
        ("extract_signals", "apply_policy_rerank"),
        ("resolve_capabilities", "apply_policy_rerank"),
    }
