from __future__ import annotations

from tests._support.fakes import FakeForgeQueryPort
from app.services.embedding.semantic_concept_embedding_service import SemanticConceptEmbeddingService


class _FakeQdrant:
    def __init__(self) -> None:
        self.ensure_calls = []
        self.points = []

    def ensure_collection(self, name, size):
        self.ensure_calls.append((name, size))

    def upsert_points(self, points, *, wait: bool = True):
        del wait
        self.points.extend(points)
        return len(points)


class _FakeModel:
    def encode(self, texts, normalize=True, batch_size=64):
        del normalize, batch_size
        return [[0.1, 0.2, 0.3] for _ in texts]


def test_rebuild_semantic_concept_index_loads_generic_rows_only() -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses = [
        [
            {
                "id": 11,
                "vertical_norm": "generic",
                "concept_key": "STUDENT_ID",
                "name": "Student Id",
                "description": "student identifier",
                "semantic_type": "identifier",
                "sub_type": None,
                "entity": "student",
                "filter_allowed": 1,
                "group_by_allowed": 1,
                "aggregation_allowed": 0,
                "is_identifier": 1,
                "is_metric": 0,
            }
        ],
        [
            {
                "alias_id": 21,
                "vertical_norm": "generic",
                "alias_key": "student number",
                "concept_key": "STUDENT_ID",
                "match_kind": "contains",
                "weight": 1.0,
                "concept_id": 11,
                "concept_name": "Student Id",
                "concept_description": "student identifier",
            }
        ],
    ]
    qdrant = _FakeQdrant()
    svc = SemanticConceptEmbeddingService(sql=sql, qdrant=qdrant, model=_FakeModel())

    result = svc.rebuild_semantic_concept_index()

    assert result == {"conceptPoints": 1, "aliasPoints": 1}
    assert len(sql.query_mappings_calls) == 2
    assert sql.query_mappings_calls[0].params is None
    assert sql.query_mappings_calls[1].params is None
    assert "vertical_norm" not in sql.query_mappings_calls[0].query
    assert "vertical_norm" not in sql.query_mappings_calls[1].query
