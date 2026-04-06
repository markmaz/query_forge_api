from __future__ import annotations

import pytest

import app.services.semantic.plan.service as plan_service_module
from app.services.semantic.plan import PlanService
from tests._support.fakes import FakeForgeQueryPort


class _Deterministic:
    def match(self, prompt):
        del prompt
        return {"matched": [], "unmatched_tokens": []}


class _ConceptRetrieval:
    def search(self, **kwargs):
        prompt = kwargs.get("prompt")
        return {"query_text": prompt, "hits": []}


class _ConceptToColumn:
    def map_concepts_to_columns(self, **kwargs):
        del kwargs
        return {"concepts": [], "mapped_columns": []}


class _DomainSelection:
    def choose_domain_id(self, **kwargs):
        del kwargs
        return {"domain_id": None}


class _ColumnVector:
    def search(self, **kwargs):
        del kwargs
        return {"filtered_to_candidate_count": 0, "hits": []}


def _build_service(*, semantic_extractor, tier2_runner=None) -> PlanService:
    return PlanService(
        sql=FakeForgeQueryPort(),
        deterministic=_Deterministic(),
        concept_retrieval=_ConceptRetrieval(),
        concept_to_column=_ConceptToColumn(),
        column_vector=_ColumnVector(),
        domain_selector=_DomainSelection(),
        llm_client=object(),
        semantic_extractor=semantic_extractor,
        tier2_runner=tier2_runner,
    )


def test_plan_includes_semantic_extract_debug_payload() -> None:
    class _SemanticExtractor:
        def extract(self, prompt):
            return {
                "normalized_text": prompt,
                "by_label": {"METRIC": ["chronically absent"], "ORG_SCHOOL": ["Holden Elementary"]},
                "slots": {"metric": ["chronically absent"], "org_schools": ["Holden Elementary"]},
                "ents": [{"start": 0, "end": 6, "label": "METRIC", "text": "absent"}],
                "warnings": [],
            }
    svc = _build_service(semantic_extractor=_SemanticExtractor())
    out = svc.plan(
        {
            "workspace_id": "ws-1",
            "vertical_norm": "education",
            "prompt": "How many chronically absent students at Holden Elementary this year?",
        },
        include_llm=False,
    )

    assert out["debug"]["semantic_extract"]["slots"]["metric"] == ["chronically absent"]
    assert out["debug"]["semantic_extract"]["slots"]["org_schools"] == ["Holden Elementary"]
    assert out["spacy"]["by_label"]["METRIC"] == ["chronically absent"]


def test_plan_degrades_when_semantic_extract_runtime_fails() -> None:
    class _BrokenSemanticExtractor:
        def extract(self, prompt):
            del prompt
            raise RuntimeError("spacy unavailable")

    svc = _build_service(semantic_extractor=_BrokenSemanticExtractor())
    out = svc.plan(
        {
            "workspace_id": "ws-1",
            "vertical_norm": "education",
            "prompt": "How many chronically absent students?",
        },
        include_llm=False,
    )

    assert "semantic_extract_failed" in out["debug"]["warnings"]
    assert out["debug"]["semantic_extract"]["warnings"] == ["semantic_extract_failed"]


def test_plan_surfaces_unexpected_semantic_extract_failures() -> None:
    class _BrokenSemanticExtractor:
        def extract(self, prompt):
            del prompt
            raise AssertionError("semantic extractor bug")

    svc = _build_service(semantic_extractor=_BrokenSemanticExtractor())

    with pytest.raises(AssertionError, match="semantic extractor bug"):
        svc.plan(
            {
                "workspace_id": "ws-1",
                "vertical_norm": "education",
                "prompt": "How many chronically absent students?",
            },
            include_llm=False,
        )


def test_plan_degrades_when_tier2_runner_runtime_fails(monkeypatch) -> None:
    monkeypatch.setattr(plan_service_module, "NLP_TIER2_ENABLED", True)

    class _SemanticExtractor:
        def extract(self, prompt):
            return {"normalized_text": prompt, "slots": {}, "ents": [], "model": {}, "warnings": []}

    def _tier2_runner(prompt):
        del prompt
        raise RuntimeError("tier2 unavailable")

    svc = _build_service(semantic_extractor=_SemanticExtractor(), tier2_runner=_tier2_runner)
    out = svc.plan(
        {
            "workspace_id": "ws-1",
            "vertical_norm": "education",
            "prompt": "How many chronically absent students?",
        },
        include_llm=False,
    )

    assert "tier2_runner_failed" in out["debug"]["warnings"]
    assert out["debug"]["tier2"]["model"]["version"] == "error"


def test_plan_surfaces_unexpected_tier2_runner_failures(monkeypatch) -> None:
    monkeypatch.setattr(plan_service_module, "NLP_TIER2_ENABLED", True)

    class _SemanticExtractor:
        def extract(self, prompt):
            return {"normalized_text": prompt, "slots": {}, "ents": [], "model": {}, "warnings": []}

    def _tier2_runner(prompt):
        del prompt
        raise AssertionError("tier2 bug")

    svc = _build_service(semantic_extractor=_SemanticExtractor(), tier2_runner=_tier2_runner)

    with pytest.raises(AssertionError, match="tier2 bug"):
        svc.plan(
            {
                "workspace_id": "ws-1",
                "vertical_norm": "education",
                "prompt": "How many chronically absent students?",
            },
            include_llm=False,
        )
