from __future__ import annotations

from app.services.forge_match.pipeline_definition import (
    build_forge_match_candidate_pipeline_definition,
    build_forge_match_row_pipeline_definition,
    build_forge_match_session_pipeline_definition,
)
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


class _RankingAdapter:
    def rank(self, *, context: PipelineContext, candidates):
        del context, candidates
        from app.services.shared_ai.artifacts import LLMDecisionArtifact

        return LLMDecisionArtifact(selected_candidate_id="10", ranked_candidate_ids=["10"], confidence=0.9, raw_payload={})


class _ConfidenceAdapter:
    def score(self, *, context: PipelineContext, candidates, decision):
        del context, candidates, decision
        from app.services.shared_ai.artifacts import ConfidenceArtifact

        return ConfidenceArtifact(confidence_score=90, confidence_band="high")


class _PersistenceAdapter:
    def persist(self, *, context: PipelineContext, outcome):
        del context, outcome
        from app.services.shared_ai.artifacts import PersistenceArtifact

        return PersistenceArtifact(record_id="sess-1:10", status="persisted")


class _SessionPreparationAdapter:
    def prepare(self, *, context: PipelineContext):
        del context
        from app.services.forge_match.session_pipeline_artifacts import ForgeMatchSessionWorkArtifact

        return ForgeMatchSessionWorkArtifact(session={"id": "sess-1"}, source_rows=[], source_total=0)


class _SessionExecutionAdapter:
    def execute(self, *, context: PipelineContext, work):
        del context, work
        from app.services.forge_match.session_pipeline_artifacts import ForgeMatchSessionExecutionArtifact

        return ForgeMatchSessionExecutionArtifact(status="completed")


class _SessionFinalizationAdapter:
    def finalize(self, *, context: PipelineContext, work, execution):
        del context, work, execution
        from app.services.forge_match.session_pipeline_artifacts import ForgeMatchSessionResultArtifact

        return ForgeMatchSessionResultArtifact(payload={"status": "analyzed"})


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


def test_forge_match_row_pipeline_definition_declares_expected_nodes_and_edges() -> None:
    definition = build_forge_match_row_pipeline_definition(
        candidate_pipeline_factory=lambda _context: build_forge_match_candidate_pipeline_definition(
            retrieval_adapter=_RetrievalAdapter(),
            capability_adapter=_CapabilityAdapter(),
            policy_adapter=_PolicyAdapter(),
        ),
        ranking_adapter=_RankingAdapter(),
        confidence_adapter=_ConfidenceAdapter(),
        persistence_adapter=_PersistenceAdapter(),
    )

    validate_pipeline_definition(definition)

    assert definition.name == "forge_match_row_pipeline"
    assert definition.start_nodes == ["dispatch_candidate_pipeline"]
    assert sorted(definition.nodes.keys()) == [
        "assemble_match_outcome",
        "dispatch_candidate_pipeline",
        "persist_match_outcome",
        "rank_candidates",
        "score_confidence",
    ]
    assert {(edge.from_node, edge.to_node) for edge in definition.edges} == {
        ("assemble_match_outcome", "persist_match_outcome"),
        ("dispatch_candidate_pipeline", "rank_candidates"),
        ("rank_candidates", "score_confidence"),
        ("score_confidence", "assemble_match_outcome"),
    }


def test_forge_match_session_pipeline_definition_declares_expected_nodes_and_edges() -> None:
    definition = build_forge_match_session_pipeline_definition(
        preparation_adapter=_SessionPreparationAdapter(),
        execution_adapter=_SessionExecutionAdapter(),
        finalization_adapter=_SessionFinalizationAdapter(),
    )

    validate_pipeline_definition(definition)

    assert definition.name == "forge_match_session_pipeline"
    assert definition.start_nodes == ["prepare_session_run"]
    assert sorted(definition.nodes.keys()) == [
        "execute_session_rows",
        "finalize_session_run",
        "prepare_session_run",
    ]
    assert {(edge.from_node, edge.to_node) for edge in definition.edges} == {
        ("execute_session_rows", "finalize_session_run"),
        ("prepare_session_run", "execute_session_rows"),
    }
