from __future__ import annotations

from app.services.shared_ai.adapters.capabilities import HeuristicColumnCapabilityAdapter
from app.services.shared_ai.adapters.candidates import candidate_from_column_row
from app.services.shared_ai.artifacts import CandidateSetArtifact
from app.services.shared_ai.context import PipelineContext
from app.services.shared_ai.nodes.resolve_capabilities import ResolveCapabilitiesNode


def test_resolve_capabilities_node_infers_column_capabilities() -> None:
    context = PipelineContext(
        pipeline_name="shared_ai_test",
        trace_id="trace-1",
        workspace_id="ws-1",
        user_id="user-1",
        vertical_norm="generic",
        request={},
    )
    context.set_artifact(
        "candidate_set",
        CandidateSetArtifact(
            candidates=[
                candidate_from_column_row(
                    {
                        "column_id": 10,
                        "column_name": "birth_date",
                        "display_name": "Birth Date",
                        "domain_id": 6,
                    }
                )
            ]
        ),
    )

    context = ResolveCapabilitiesNode(adapter=HeuristicColumnCapabilityAdapter()).run(context)

    capability_map = context.artifacts["capability_map"]
    enriched = context.artifacts["capability_enriched_candidates"]
    assert capability_map.candidate_capabilities["10"] == ["BIRTH_DATE"]
    assert enriched.candidates[0].capabilities == ["BIRTH_DATE"]
