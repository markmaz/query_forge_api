from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List

from app.services.semantic.concept_retrieval_service import ConceptRetrievalService


@dataclass
class _Hit:
    score: float
    payload: Dict[str, Any]


class _FakeQdrant:
    def __init__(self, hits: List[_Hit]) -> None:
        self._hits = hits
        self.query_filters = []

    def search(self, *, vector, limit, query_filter, with_payload):
        del vector, limit, with_payload
        self.query_filters.append(query_filter)
        return self._hits


class _FakeModel:
    def encode(self, texts, normalize=True):
        del texts, normalize
        return [[0.1, 0.2, 0.3]]


def test_concept_vector_dedup() -> None:
    qdrant = _FakeQdrant(
        [
            _Hit(0.81, {"type": "concept", "concept_key": "GRADE_LEVEL", "concept_id": 10}),
            _Hit(0.77, {"type": "alias", "concept_key": "GRADE_LEVEL", "alias_key": "grade", "concept_id": 10, "weight": 1.0}),
            _Hit(0.74, {"type": "alias", "concept_key": "RACE", "alias_key": "black", "concept_id": 11, "weight": 1.0}),
        ]
    )
    svc = ConceptRetrievalService(qdrant=qdrant, model=_FakeModel())

    out = svc.search(prompt="black students by grade", max_concepts=5)
    hits = out["hits"]
    assert len([h for h in hits if h["concept_key"] == "GRADE_LEVEL"]) == 1
    assert any(h["concept_key"] == "RACE" for h in hits)
    assert len(qdrant.query_filters[0].must) == 1
