from __future__ import annotations

from app.services.shared_ai.adapters.candidates import candidate_from_column_row
from app.services.shared_ai.adapters.policies import PlannerPolicyRerankAdapter
from app.services.shared_ai.artifacts import CandidateSetArtifact, CapabilityMapArtifact, PromptSignalsArtifact
from app.services.shared_ai.context import PipelineContext
from app.services.shared_ai.nodes.apply_policy_rerank import ApplyPolicyRerankNode


class _FakePolicyService:
    def get_applicable_policies(self, *, workspace_id: str, vertical_norm: str, base_domain_id: int):
        del workspace_id, vertical_norm
        if base_domain_id != 6:
            return []
        return [
            {
                "policy_key": "birth_month_birthdate",
                "stop_on_match": False,
                "policy_json": {
                    "when_signals_all": ["birth_month_prompt"],
                    "when_signals_any": [],
                    "exclude_signals_any": [],
                    "prefer_capabilities": ["BIRTH_DATE"],
                    "penalize_missing": ["BIRTH_DATE"],
                    "require_for_bonus": [],
                    "boost": 0.2,
                    "penalty": 0.3,
                    "max_effect": 0.3,
                },
            }
        ]


def test_apply_policy_rerank_node_reranks_candidates() -> None:
    birth_date = candidate_from_column_row(
        {
            "column_id": 10,
            "column_name": "birth_date",
            "display_name": "Birth Date",
            "domain_id": 6,
            "combined_retrieval_score": 0.5,
        }
    )
    k_student = candidate_from_column_row(
        {
            "column_id": 11,
            "column_name": "k_student",
            "display_name": "Student Key",
            "domain_id": 6,
            "combined_retrieval_score": 0.55,
        }
    )
    context = PipelineContext(
        pipeline_name="shared_ai_test",
        trace_id="trace-1",
        workspace_id="ws-1",
        user_id="user-1",
        vertical_norm="generic",
        request={},
    )
    context.set_artifact("capability_enriched_candidates", CandidateSetArtifact(candidates=[birth_date, k_student]))
    context.set_artifact(
        "prompt_signals",
        PromptSignalsArtifact(
            source_text="Show me all the students who have a birthday in March",
            normalized_text="show me all the students who have a birthday in march",
            signals=["birth_month_prompt", "student_listing"],
        ),
    )
    context.set_artifact(
        "capability_map",
        CapabilityMapArtifact(
            candidate_capabilities={
                "10": ["BIRTH_DATE"],
                "11": ["STUDENT_IDENTITY"],
            }
        ),
    )

    context = ApplyPolicyRerankNode(
        adapter=PlannerPolicyRerankAdapter(policy_service=_FakePolicyService())
    ).run(context)

    reranked = context.artifacts["reranked_candidates"]
    assert reranked.candidates[0].candidate_id == "10"
    assert reranked.candidates[0].scores["final_score"] > reranked.candidates[1].scores["final_score"]
    assert reranked.policy_effects[0]["policy_key"] == "birth_month_birthdate"
