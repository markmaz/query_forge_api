from __future__ import annotations

from app.services.planner.semantic_candidate_models import SemanticCandidatePayload, SemanticConceptCandidate
from app.services.planner.semantic_grounding_service import SemanticGroundingService


class _FakeRetrievalService:
    def __init__(self) -> None:
        self.calls = []

    def retrieve(self, **kwargs):
        self.calls.append(dict(kwargs))
        return SemanticCandidatePayload(
            prompt="students by county",
            workspace_id="ws-1",
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
    def __init__(self) -> None:
        self.calls = []

    def resolve(self, *, prompt: str, workspace_id: str | None = None):
        self.calls.append({"prompt": prompt, "workspace_id": workspace_id})
        return [
            {
                "concept_key": "COUNTRY",
                "canonical_value": "United States",
                "matched_alias": "US",
            }
        ]


def test_build_grounding_bundle_combines_candidates_and_alias_constraints() -> None:
    retrieval = _FakeRetrievalService()
    resolver = _FakeValueAliasResolver()
    svc = SemanticGroundingService(
        retrieval_service=retrieval,
        value_alias_resolver=resolver,
    )

    out = svc.build_grounding_bundle(
        prompt="students by county not born in the US",
        workspace_id="ws-1",
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
    assert "vertical_norm" not in retrieval.calls[0]
    assert resolver.calls[0]["prompt"] == "students by county not born in the US"
    assert resolver.calls[0]["workspace_id"] == "ws-1"


class _RaisingRetrievalService:
    def retrieve(self, **kwargs):
        del kwargs
        raise RuntimeError("semantic retrieval unavailable")


class _RaisingAliasResolver:
    def resolve(self, *, prompt: str, workspace_id: str | None = None):
        del prompt, workspace_id
        raise RuntimeError("alias resolution unavailable")


class _LegacyValueAliasResolver:
    def __init__(self) -> None:
        self.calls = []

    def resolve(self, *, prompt: str):
        self.calls.append({"prompt": prompt})
        return [
            {
                "concept_key": "RACE_ETHNICITY",
                "kind": "unknown",
                "text": "african american",
                "op": "eq",
                "value_hint": "Black or African American",
                "notes": "semantic_alias:RACE_ETHNICITY",
            }
        ]


def test_build_grounding_bundle_marks_candidate_retrieval_failure() -> None:
    svc = SemanticGroundingService(
        retrieval_service=_RaisingRetrievalService(),
        value_alias_resolver=_FakeValueAliasResolver(),
    )

    out = svc.build_grounding_bundle(
        prompt="students by county",
        workspace_id="ws-1",
        base_domain_id=6,
        base_domain_name="Enrollment",
        capabilities_compact={"dimensions": [], "filter_columns": [], "time_columns": []},
    )

    assert out.candidates is None
    assert out.warnings == ["candidate_retrieval_failed"]
    assert out.alias_constraints


def test_resolve_alias_constraints_returns_empty_on_resolver_failure() -> None:
    svc = SemanticGroundingService(
        retrieval_service=_FakeRetrievalService(),
        value_alias_resolver=_RaisingAliasResolver(),
    )

    out = svc.resolve_alias_constraints(
        prompt="students by county",
    )

    assert out == []


def test_resolve_alias_constraints_supports_legacy_resolver_signature_without_workspace() -> None:
    resolver = _LegacyValueAliasResolver()
    svc = SemanticGroundingService(
        retrieval_service=_FakeRetrievalService(),
        value_alias_resolver=resolver,
    )

    out = svc.resolve_alias_constraints(
        prompt="show me african american students",
        workspace_id="ws-1",
    )

    assert out == [
        {
            "kind": "unknown",
            "text": "african american",
            "op": "eq",
            "value_hint": "Black or African American",
            "notes": "semantic_alias:RACE_ETHNICITY",
        }
    ]
    assert resolver.calls == [{"prompt": "show me african american students"}]


def test_resolve_alias_constraints_accepts_legacy_alias_constraint_rows() -> None:
    svc = SemanticGroundingService(
        retrieval_service=_FakeRetrievalService(),
        value_alias_resolver=_LegacyValueAliasResolver(),
    )

    out = svc.resolve_alias_constraints(prompt="show me african american students")

    assert out[0]["value_hint"] == "Black or African American"
    assert out[0]["text"] == "african american"
    assert out[0]["notes"] == "semantic_alias:RACE_ETHNICITY"
