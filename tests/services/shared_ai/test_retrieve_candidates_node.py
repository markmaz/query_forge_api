from __future__ import annotations

from app.services.shared_ai.artifacts import Candidate, CandidateSetArtifact
from app.services.shared_ai.context import PipelineContext
from app.services.shared_ai.nodes.retrieve_candidates import RetrieveCandidatesNode


class _Adapter:
    def retrieve(self, *, context: PipelineContext) -> CandidateSetArtifact:
        assert context.request["prompt"] == "birth date"
        return CandidateSetArtifact(
            candidates=[
                Candidate(
                    candidate_id="1",
                    candidate_type="column",
                    label="Birth Date",
                )
            ],
            retrieval_debug={"source": "test"},
        )


def test_retrieve_candidates_node_sets_candidate_artifact_and_debug() -> None:
    context = PipelineContext(
        pipeline_name="test_pipeline",
        trace_id="trace-1",
        workspace_id="ws-1",
        user_id="user-1",
        request={"prompt": "birth date"},
    )

    out = RetrieveCandidatesNode(adapter=_Adapter()).run(context)

    artifact = out.get_artifact("candidate_set", node_name="retrieve_candidates")
    assert isinstance(artifact, CandidateSetArtifact)
    assert artifact.candidates[0].label == "Birth Date"
    assert out.debug["retrieve_candidates"]["candidate_count"] == 1
