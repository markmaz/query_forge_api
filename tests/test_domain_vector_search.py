from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, List

from app.services.vector import DomainVectorIndexService
from tests._support.fakes import FakeForgeQueryPort


@dataclass
class _Hit:
    id: int
    score: float
    payload: Dict[str, Any]


class _FakeQdrant:
    def __init__(self) -> None:
        self.collection = None
        self.vector_size = None
        self.payload_indexes: List[str] = []
        self.points: Dict[int, Dict[str, Any]] = {}

    def ensure_collection(self, name: str, vector_size: int) -> None:
        self.collection = name
        self.vector_size = int(vector_size)

    def ensure_payload_index(self, *, key: str, schema) -> None:
        del schema
        self.payload_indexes.append(key)

    def upsert_points(self, points, *, wait: bool = True) -> int:
        del wait
        count = 0
        for point in points:
            self.points[int(point.id)] = {
                "id": int(point.id),
                "vector": list(point.vector),
                "payload": dict(point.payload or {}),
            }
            count += 1
        return count

    def search(self, *, vector, limit, query_filter, with_payload=True):
        del with_payload
        matches: List[_Hit] = []
        for item in self.points.values():
            payload = item["payload"]
            if not _matches_filter(payload, query_filter):
                continue
            score = _dot(vector, item["vector"])
            matches.append(_Hit(id=item["id"], score=score, payload=payload))
        matches.sort(key=lambda row: (-float(row.score), int(row.id)))
        return matches[: int(limit)]


class _FakeEmbeddingModel:
    dimension = 8

    def encode(self, texts, *, normalize: bool = True, batch_size: int = 64):
        del batch_size
        vectors = [_embed_text(text) for text in texts]
        if normalize:
            vectors = [_normalize(v) for v in vectors]
        return vectors


def _matches_filter(payload: Dict[str, Any], query_filter) -> bool:
    for cond in getattr(query_filter, "must", []) or []:
        key = getattr(cond, "key", None)
        match = getattr(cond, "match", None)
        expected = getattr(match, "value", None)
        if key is None:
            continue
        if payload.get(key) != expected:
            return False
    return True


def _embed_text(text: str) -> List[float]:
    t = str(text or "").lower()
    feats = [
        1.0 if "student" in t else 0.0,
        1.0 if "teacher" in t else 0.0,
        1.0 if "enrollment" in t else 0.0,
        1.0 if "attendance" in t else 0.0,
        1.0 if "district" in t else 0.0,
        1.0 if "staff" in t else 0.0,
        1.0 if "health" in t else 0.0,
        1.0 if "claim" in t else 0.0,
    ]
    return feats


def _normalize(values: List[float]) -> List[float]:
    norm = math.sqrt(sum(v * v for v in values))
    if norm <= 0:
        return values
    return [v / norm for v in values]


def _dot(a: List[float], b: List[float]) -> float:
    return float(sum(x * y for x, y in zip(a, b)))


def _service() -> DomainVectorIndexService:
    return DomainVectorIndexService(
        sql=FakeForgeQueryPort(),
        qdrant=_FakeQdrant(),
        model=_FakeEmbeddingModel(),
        collection_name="domain_catalog_v1",
    )


def test_domain_vector_search_filters_vertical_and_workspace() -> None:
    svc = _service()
    svc.ensure_collection()
    svc.upsert_domains(
        [
            {
                "domain_id": 7,
                "workspace_id": "ws-1",
                "vertical_norm": "education",
                "name": "Enrollment",
                "summary": "Student enrollment facts",
                "embedding_text": "student enrollment by district and school year",
                "domain_version": 3,
                "is_active": True,
                "table_count": 4,
                "join_edge_count": 3,
                "keywords": ["students", "enrollment"],
            },
            {
                "domain_id": 8,
                "workspace_id": "ws-1",
                "vertical_norm": "healthcare",
                "name": "Claims",
                "summary": "Medical claims",
                "embedding_text": "health claims and billing",
                "domain_version": 5,
                "is_active": True,
                "table_count": 2,
                "join_edge_count": 1,
                "keywords": ["claims"],
            },
            {
                "domain_id": 9,
                "workspace_id": "ws-2",
                "vertical_norm": "education",
                "name": "Other workspace",
                "summary": "Other workspace domain",
                "embedding_text": "student attendance",
                "domain_version": 1,
                "is_active": True,
                "table_count": 2,
                "join_edge_count": 1,
                "keywords": ["attendance"],
            },
        ],
        force=True,
    )

    out = svc.search_domains(
        workspace_id="ws-1",
        query="student enrollment",
        vertical_norm="education",
        limit=5,
        score_threshold=0.0,
        include_payload=False,
    )

    assert len(out["results"]) == 1
    assert out["results"][0]["domain_id"] == 7
    assert "student" in out["results"][0]["reason"]


def test_domain_vector_search_stable_order_by_score_then_id() -> None:
    svc = _service()
    svc.ensure_collection()
    svc.upsert_domains(
        [
            {
                "domain_id": 11,
                "workspace_id": "ws-1",
                "vertical_norm": "education",
                "name": "Enrollment",
                "summary": "Enrollment",
                "embedding_text": "student enrollment",
                "domain_version": 1,
                "is_active": True,
                "table_count": 1,
                "join_edge_count": 1,
            },
            {
                "domain_id": 12,
                "workspace_id": "ws-1",
                "vertical_norm": "education",
                "name": "Teacher staffing",
                "summary": "Teacher staffing",
                "embedding_text": "teacher staff district",
                "domain_version": 1,
                "is_active": True,
                "table_count": 1,
                "join_edge_count": 1,
            },
            {
                "domain_id": 13,
                "workspace_id": "ws-1",
                "vertical_norm": "education",
                "name": "Attendance",
                "summary": "Attendance",
                "embedding_text": "student attendance",
                "domain_version": 1,
                "is_active": True,
                "table_count": 1,
                "join_edge_count": 1,
            },
        ],
        force=True,
    )

    out = svc.search_domains(
        workspace_id="ws-1",
        query="student enrollment",
        vertical_norm="education",
        limit=3,
        score_threshold=0.0,
        include_payload=False,
    )
    ordered_ids = [item["domain_id"] for item in out["results"]]
    assert ordered_ids == [11, 13, 12]


def test_domain_vector_search_returns_payload_fields() -> None:
    svc = _service()
    svc.ensure_collection()
    svc.upsert_domains(
        [
            {
                "domain_id": 21,
                "workspace_id": "ws-1",
                "vertical_norm": "education",
                "name": "Enrollment",
                "summary": "Student enrollment facts",
                "embedding_text": "student enrollment by district",
                "domain_version": 4,
                "is_active": True,
                "table_count": 7,
                "join_edge_count": 5,
                "keywords": ["students", "enrollment", "district"],
            }
        ],
        force=True,
    )

    out = svc.search_domains(
        workspace_id="ws-1",
        query="district enrollment",
        vertical_norm="education",
        limit=1,
        score_threshold=0.0,
        include_payload=True,
    )
    row = out["results"][0]
    assert row["domain_id"] == 21
    assert row["name"] == "Enrollment"
    assert row["domain_version"] == 4
    assert row["table_count"] == 7
    assert row["join_edge_count"] == 5
    assert isinstance(row.get("payload"), dict)
    assert row["payload"]["vertical_norm"] == "education"
