from __future__ import annotations

from app.services.semantic.plan_service import PlanService
from tests._support.fakes import FakeSQLExecutor


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

    svc = PlanService(
        sql=FakeSQLExecutor(),
        deterministic=_Deterministic(),
        concept_retrieval=_ConceptRetrieval(),
        concept_to_column=_ConceptToColumn(),
        column_vector=_ColumnVector(),
        domain_selector=_DomainSelection(),
        llm_client=object(),
        semantic_extractor=_SemanticExtractor(),
    )
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
