from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from app.services.semantic.constrained_column_vector_service import ConstrainedColumnVectorService
from tests._support.fakes import FakeSQLExecutor


@dataclass
class _Hit:
    score: float
    payload: Dict[str, Any]


class _FakeQdrant:
    def __init__(self, hits: List[_Hit]) -> None:
        self.hits = hits
        self.last_filter = None

    def search(self, *, vector, limit, query_filter, with_payload):
        del vector, limit, with_payload
        self.last_filter = query_filter
        return self.hits


class _FakeModel:
    def encode(self, texts, normalize=True):
        del normalize
        return [[0.1, 0.2, 0.3] for _ in texts]


def _match_any_values(query_filter) -> Optional[List[int]]:
    for cond in getattr(query_filter, "must", []) or []:
        if getattr(cond, "key", "") == "model_column_id":
            match = getattr(cond, "match", None)
            return list(getattr(match, "any", []) or [])
    return None


def test_constrained_vector_search_filters_ids() -> None:
    qdrant = _FakeQdrant(
        [
            _Hit(0.82, {"model_column_id": 101, "table_name": "dim_student", "column_name": "grade_level"}),
            _Hit(0.75, {"model_column_id": 999, "table_name": "dim_other", "column_name": "bad"}),
        ]
    )
    svc = ConstrainedColumnVectorService(qdrant=qdrant, model=_FakeModel())

    out = svc.search(
        prompt="students by grade",
        workspace_id="ws-1",
        candidate_columns=[
            {"model_column_id": 101, "workspace_table_id": 42, "table_name": "dim_student", "column_name": "grade_level", "concept_key": "GRADE_LEVEL", "weight": 1.0},
            {"model_column_id": 102, "workspace_table_id": 42, "table_name": "dim_student", "column_name": "race", "concept_key": "RACE", "weight": 1.0},
        ],
        concept_hits=[{"concept_key": "GRADE_LEVEL"}],
        max_columns=10,
    )

    assert out["filtered_to_candidate_count"] == 2
    assert len(out["hits"]) == 1
    assert out["hits"][0]["workspace_table_id"] == 42
    values = _match_any_values(qdrant.last_filter)
    assert values == [101, 102]


def test_constrained_vector_search_applies_domain_workspace_table_filter() -> None:
    qdrant = _FakeQdrant(
        [
            _Hit(0.82, {"model_column_id": 101, "table_name": "dim_student", "column_name": "grade_level"}),
            _Hit(0.75, {"model_column_id": 102, "table_name": "dim_student", "column_name": "race"}),
        ]
    )
    sql = FakeSQLExecutor()
    sql.query_mappings_responses = [[{"workspace_table_id": 42}]]
    svc = ConstrainedColumnVectorService(qdrant=qdrant, model=_FakeModel(), sql=sql)

    out = svc.search(
        prompt="students by grade",
        workspace_id="ws-1",
        candidate_columns=[
            {"model_column_id": 101, "workspace_table_id": 42, "table_name": "dim_student", "column_name": "grade_level", "concept_key": "GRADE_LEVEL", "weight": 1.0},
            {"model_column_id": 102, "workspace_table_id": 99, "table_name": "dim_student", "column_name": "race", "concept_key": "RACE", "weight": 1.0},
        ],
        concept_hits=[{"concept_key": "GRADE_LEVEL"}],
        max_columns=10,
        domain_id=7,
    )

    assert out["filtered_to_candidate_count"] == 1
    assert len(out["hits"]) == 1
    assert out["hits"][0]["model_column_id"] == 101
    values = _match_any_values(qdrant.last_filter)
    assert values == [101]
