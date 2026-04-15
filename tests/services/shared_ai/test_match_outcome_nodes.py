from __future__ import annotations

from app.services.shared_ai.artifacts import (
    Candidate,
    ConfidenceArtifact,
    LLMDecisionArtifact,
    MatchOutcomeArtifact,
    PersistenceArtifact,
    RerankedCandidatesArtifact,
)
from app.services.shared_ai.context import PipelineContext
from app.services.shared_ai.nodes.assemble_match_outcome import AssembleMatchOutcomeNode
from app.services.shared_ai.nodes.persist_match_outcome import PersistMatchOutcomeNode


class _PersistenceAdapter:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def persist(self, *, context: PipelineContext, outcome: MatchOutcomeArtifact) -> PersistenceArtifact:
        self.calls.append(
            {
                "workspace_id": context.workspace_id,
                "selected_column_id": outcome.selected_candidate.get("column_id") if outcome.selected_candidate else None,
            }
        )
        return PersistenceArtifact(record_id="sess-1:10", status="persisted")


def _context() -> PipelineContext:
    context = PipelineContext(
        pipeline_name="forge_match_row_pipeline",
        trace_id="trace-1",
        workspace_id="ws-1",
        user_id=None,
        request={},
    )
    context.set_artifact(
        "reranked_candidates",
        RerankedCandidatesArtifact(
            candidates=[
                Candidate(
                    candidate_id="202",
                    candidate_type="column",
                    label="Birth Date",
                    attributes={"column_id": 202, "column_name": "birth_date"},
                ),
                Candidate(
                    candidate_id="101",
                    candidate_type="column",
                    label="Program Name",
                    attributes={"column_id": 101, "column_name": "program_name"},
                ),
            ]
        ),
    )
    context.set_artifact(
        "llm_decision",
        LLMDecisionArtifact(
            selected_candidate_id="202",
            ranked_candidate_ids=["202", "101"],
            confidence=0.88,
            raw_payload={"selected_column_id": 202, "alternate_column_ids": [101]},
        ),
    )
    context.set_artifact(
        "confidence",
        ConfidenceArtifact(confidence_score=86, confidence_band="high", details={"confidence_score": 86}),
    )
    context.trace_nodes.append({"node": "score_confidence"})
    return context


def test_assemble_match_outcome_node_builds_match_payload() -> None:
    out = AssembleMatchOutcomeNode(include_pipeline_snapshot=True).run(_context())

    artifact = out.get_artifact("match_outcome", node_name="assert")
    assert isinstance(artifact, MatchOutcomeArtifact)
    assert artifact.selected_candidate["column_id"] == 202
    assert artifact.alternates[0]["column_id"] == 101
    assert artifact.decision_payload["shared_pipeline"]["trace_nodes"][-1]["node"] == "score_confidence"
    assert out.debug["assemble_match_outcome"]["selected_candidate_id"] == "202"


def test_persist_match_outcome_node_stores_persistence_artifact() -> None:
    adapter = _PersistenceAdapter()
    context = _context()
    context = AssembleMatchOutcomeNode(include_pipeline_snapshot=True).run(context)

    out = PersistMatchOutcomeNode(adapter=adapter).run(context)

    artifact = out.get_artifact("persistence_result", node_name="assert")
    assert isinstance(artifact, PersistenceArtifact)
    assert artifact.record_id == "sess-1:10"
    assert adapter.calls[0]["selected_column_id"] == 202
    assert out.debug["persist_match_outcome"]["status"] == "persisted"
