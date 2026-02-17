from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from qdrant_client.http import models as qdrant_models

from app.config import QDRANT_COLUMN_COLLECTION, QDRANT_COLUMN_COLLECTION_V2
from app.infra.embedding_model import EmbeddingModel
from app.infra.qdrant_client import QdrantClientWrapper

COLUMN_COLLECTION_NAME = QDRANT_COLUMN_COLLECTION_V2 or QDRANT_COLUMN_COLLECTION or "column_catalog_v2"


class ConstrainedColumnVectorService:
    def __init__(
        self,
        *,
        qdrant: Optional[QdrantClientWrapper] = None,
        model: Optional[EmbeddingModel] = None,
    ) -> None:
        self._qdrant = qdrant or QdrantClientWrapper(collection_name=COLUMN_COLLECTION_NAME)
        self._model = model or EmbeddingModel()

    def search(
        self,
        *,
        prompt: str,
        workspace_id: str,
        candidate_columns: Sequence[Dict[str, Any]],
        concept_hits: Sequence[Dict[str, Any]],
        max_columns: int,
    ) -> Dict[str, Any]:
        candidate_by_id: Dict[int, Dict[str, Any]] = {}
        for row in candidate_columns:
            try:
                model_column_id = int(row.get("model_column_id"))
            except Exception:
                continue
            existing = candidate_by_id.get(model_column_id)
            if existing is None or float(existing.get("weight") or 0.0) < float(row.get("weight") or 0.0):
                candidate_by_id[model_column_id] = dict(row)

        candidate_ids = sorted(candidate_by_id.keys())
        if not candidate_ids:
            return {
                "filtered_to_candidate_count": 0,
                "hits": [],
            }

        max_cols = max(1, min(200, int(max_columns or 60)))
        query_texts = [str(prompt or "").strip()]
        for hit in concept_hits[:8]:
            concept_key = str(hit.get("concept_key") or "").strip().lower()
            if concept_key:
                query_texts.append(concept_key.replace("_", " "))

        vectors = self._model.encode(query_texts, normalize=True)
        query_filter = qdrant_models.Filter(
            must=[
                qdrant_models.FieldCondition(
                    key="kind",
                    match=qdrant_models.MatchValue(value="column"),
                ),
                qdrant_models.FieldCondition(
                    key="workspace_id",
                    match=qdrant_models.MatchValue(value=str(workspace_id)),
                ),
                qdrant_models.FieldCondition(
                    key="model_column_id",
                    match=qdrant_models.MatchAny(any=candidate_ids),
                ),
            ]
        )

        by_id: Dict[int, Dict[str, Any]] = {}
        for vector in vectors:
            points = self._qdrant.search(
                vector=vector,
                limit=max_cols,
                query_filter=query_filter,
                with_payload=True,
            )
            for point in points:
                payload = point.payload or {}
                model_column_id = _to_int_or_none(payload.get("model_column_id"))
                if model_column_id is None or model_column_id not in candidate_by_id:
                    continue
                score = float(point.score or 0.0)
                existing = by_id.get(model_column_id)
                if existing is not None and float(existing.get("score") or 0.0) >= score:
                    continue
                mapped = candidate_by_id[model_column_id]
                by_id[model_column_id] = {
                    "model_column_id": model_column_id,
                    "score": round(score, 4),
                    "table_name": payload.get("table_name") or mapped.get("table_name"),
                    "column_name": payload.get("column_name") or mapped.get("column_name"),
                    "concept_key": mapped.get("concept_key"),
                }

        hits = sorted(by_id.values(), key=lambda row: float(row.get("score") or 0.0), reverse=True)[:max_cols]
        return {
            "filtered_to_candidate_count": len(candidate_ids),
            "hits": hits,
        }


def _to_int_or_none(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except Exception:
        return None


__all__ = ["ConstrainedColumnVectorService"]
