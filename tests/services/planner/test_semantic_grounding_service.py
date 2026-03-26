from __future__ import annotations

from app.services.planner.semantic_candidate_models import SemanticCandidatePayload, SemanticConceptCandidate
from app.services.planner.semantic_grounding_service import SemanticGroundingService


class _FakeRetrievalService:
    def retrieve(self, **kwargs):
        del kwargs
        return SemanticCandidatePayload(
            prompt="students by county",
            workspace_id="ws-1",
            vertical_norm="education",
            base_domain_id=6,
            base_domain_key="ENROLLMENT",
            metric_candidates=[
                SemanticConceptCandidate(
                    concept_key="ENROLLMENT_COUNT",
                    label="Enrollment Count",
                    metric_ref="domain_metric:enrollment_count",
                )
            ],
            dimension_candidates=[
                SemanticConceptCandidate(
                    concept_key="COUNTY",
                    label="County",
                    source_column_key="wt20.county_fips_code",
                )
            ],
            filter_candidates=[
                SemanticConceptCandidate(
                    concept_key="COUNTY",
                    label="County",
                    source_column_key="wt20.county_fips_code",
                )
            ],
            metadata={"semantic_source": "registry"},
        )


class _FakeValueAliasResolver:
    def resolve(self, *, prompt: str, vertical_norm: str):
        del prompt, vertical_norm
        return [
            {
                "concept_key": "COUNTRY",
                "canonical_value": "United States",
                "matched_alias": "US",
            }
        ]


def test_build_grounding_bundle_combines_candidates_and_alias_constraints() -> None:
    svc = SemanticGroundingService(
        retrieval_service=_FakeRetrievalService(),
        value_alias_resolver=_FakeValueAliasResolver(),
    )

    out = svc.build_grounding_bundle(
        prompt="students by county not born in the US",
        workspace_id="ws-1",
        vertical_norm="education",
        base_domain_id=6,
        base_domain_name="Enrollment",
        capabilities_compact={"dimensions": [], "filter_columns": [], "time_columns": []},
    )

    debug = out.to_debug_payload()
    assert debug["alias_constraints"][0]["value_hint"] == "United States"
    assert debug["candidate_summary"]["semantic_source"] == "registry"
    assert debug["candidate_summary"]["metric_count"] == 1
    assert debug["candidate_summary"]["dimension_count"] == 1
    assert debug["candidate_summary"]["metrics"] == ["ENROLLMENT_COUNT"]
