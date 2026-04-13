from __future__ import annotations

from typing import Any, Dict, Optional, Sequence

from qdrant_client.http import models as qdrant_models

from app.config import QDRANT_SEMANTIC_CONCEPT_COLLECTION
from app.infra.embedding_model import EmbeddingModel
from app.infra.qdrant_client import QdrantClientWrapper
from app.services.semantic.vertical_norm import normalize_semantic_vertical

COLLECTION_NAME = QDRANT_SEMANTIC_CONCEPT_COLLECTION or "semantic_concepts_v1"


class ConceptRetrievalService:
    def __init__(
        self,
        *,
        qdrant: Optional[QdrantClientWrapper] = None,
        model: Optional[EmbeddingModel] = None,
    ) -> None:
        self._qdrant = qdrant or QdrantClientWrapper(collection_name=COLLECTION_NAME)
        self._model = model or EmbeddingModel()

    def search(
        self,
        *,
        prompt: str,
        vertical_norm: str,
        max_concepts: int,
        deterministic_matches: Optional[Sequence[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        query_text = (prompt or "").strip()
        limit = max(1, min(100, int(max_concepts) * 4))
        vertical = _norm_vertical(vertical_norm)

        vector = self._model.encode([query_text], normalize=True)[0]
        query_filter = qdrant_models.Filter(
            must=[
                qdrant_models.FieldCondition(
                    key="type",
                    match=qdrant_models.MatchAny(any=["concept", "alias"]),
                ),
                qdrant_models.FieldCondition(
                    key="vertical_norm",
                    match=qdrant_models.MatchAny(any=[vertical, "generic"]),
                ),
            ]
        )

        scored_points = self._qdrant.search(
            vector=vector,
            limit=limit,
            query_filter=query_filter,
            with_payload=True,
        )

        by_key: Dict[str, Dict[str, Any]] = {}
        for hit in scored_points:
            payload = hit.payload or {}
            concept_key = str(payload.get("concept_key") or "").strip().upper()
            if concept_key == "":
                continue
            source = str(payload.get("type") or "concept").strip().lower()
            score = float(hit.score or 0.0)
            if source == "alias":
                score = min(1.0, score * (1.0 + (float(payload.get("weight") or 0.0) * 0.15)))
            existing = by_key.get(concept_key)
            if existing is None or float(existing["score"]) < score:
                by_key[concept_key] = {
                    "concept_key": concept_key,
                    "concept_id": _to_int_or_none(payload.get("concept_id")),
                    "score": round(score, 4),
                    "source": source,
                    "alias_key": payload.get("alias_key") if source == "alias" else None,
                }

        for item in deterministic_matches or []:
            concept_key = str(item.get("concept_key") or "").strip().upper()
            if concept_key == "":
                continue
            det_score = max(0.9, float(item.get("confidence") or 0.9))
            existing = by_key.get(concept_key)
            if existing is None or float(existing["score"]) < det_score:
                by_key[concept_key] = {
                    "concept_key": concept_key,
                    "concept_id": None,
                    "score": round(det_score, 4),
                    "source": "deterministic",
                    "alias_key": None,
                }

        hits = sorted(by_key.values(), key=lambda row: float(row["score"]), reverse=True)[: max(1, int(max_concepts))]
        return {
            "query_text": query_text,
            "hits": hits,
        }


def _norm_vertical(vertical_norm: str) -> str:
    return normalize_semantic_vertical(vertical_norm)


def _to_int_or_none(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


__all__ = ["ConceptRetrievalService"]
