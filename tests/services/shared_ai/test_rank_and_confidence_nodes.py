from __future__ import annotations

from app.services.shared_ai.artifacts import CandidateSetArtifact, ConfidenceArtifact, LLMDecisionArtifact
from app.services.shared_ai.context import PipelineContext
from app.services.shared_ai.nodes.rank_candidates import RankCandidatesNode
from app.services.shared_ai.nodes.score_confidence import ScoreConfidenceNode


class _RankingAdapter:
    def rank(self, *, context: PipelineContext, candidates: CandidateSetArtifact) -> LLMDecisionArtifact:
        del context, candidates
        return LLMDecisionArtifact(
            selected_candidate_id="202",
            ranked_candidate_ids=["202", "101"],
            confidence=0.88,
            raw_payload={"selected_column_id": 202},
        )


class _ConfidenceAdapter:
    def score(
        self,
        *,
        context: PipelineContext,
        candidates: CandidateSetArtifact,
        decision: LLMDecisionArtifact,
    ) -> ConfidenceArtifact:
        del context, candidates, decision
        return ConfidenceArtifact(confidence_score=86, confidence_band="high")


def _context() -> PipelineContext:
    context = PipelineContext(
        pipeline_name="shared_ai_test",
        trace_id="trace-1",
        workspace_id="ws-1",
        user_id="user-1",
        vertical_norm="education",
        request={},
    )
    context.set_artifact("reranked_candidates", CandidateSetArtifact())
    return context


def test_rank_candidates_node_stores_llm_decision_artifact() -> None:
    context = RankCandidatesNode(adapter=_RankingAdapter()).run(_context())

    artifact = context.get_artifact("llm_decision", node_name="assert")
    assert isinstance(artifact, LLMDecisionArtifact)
    assert artifact.selected_candidate_id == "202"
    assert context.debug["rank_candidates"]["selected_candidate_id"] == "202"


def test_score_confidence_node_stores_confidence_artifact() -> None:
    context = _context()
    context.set_artifact(
        "llm_decision",
        LLMDecisionArtifact(selected_candidate_id="202", ranked_candidate_ids=["202"], confidence=0.88, raw_payload={}),
    )

    out = ScoreConfidenceNode(adapter=_ConfidenceAdapter()).run(context)

    artifact = out.get_artifact("confidence", node_name="assert")
    assert isinstance(artifact, ConfidenceArtifact)
    assert artifact.confidence_score == 86
    assert out.debug["score_confidence"]["confidence_band"] == "high"
