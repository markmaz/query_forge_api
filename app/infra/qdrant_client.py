from __future__ import annotations

import logging
from typing import Iterable, Optional, Sequence

from qdrant_client import QdrantClient
from qdrant_client.http import models as qdrant_models
from qdrant_client.http.exceptions import UnexpectedResponse

from app.config import QDRANT_API_KEY, QDRANT_TIMEOUT_S, QDRANT_URL

logger = logging.getLogger(__name__)


class QdrantClientWrapper:
    def __init__(
        self,
        *,
        url: Optional[str] = None,
        api_key: Optional[str] = None,
        timeout_s: Optional[int] = None,
        collection_name: Optional[str] = None,
    ) -> None:
        self._collection_name = collection_name
        self._client = QdrantClient(
            url=(url or QDRANT_URL),
            api_key=(api_key or QDRANT_API_KEY or None),
            timeout=timeout_s or QDRANT_TIMEOUT_S,
        )

    def ensure_collection(self, name: str, vector_size: int) -> None:
        if self._collection_name is None:
            self._collection_name = name

        try:
            info = self._client.get_collection(name)
        except UnexpectedResponse as exc:
            if exc.status_code != 404:
                raise
            logger.info("Creating Qdrant collection %s (size=%s, distance=cosine)", name, vector_size)
            self._client.create_collection(
                collection_name=name,
                vectors_config=qdrant_models.VectorParams(
                    size=vector_size,
                    distance=qdrant_models.Distance.COSINE,
                ),
            )
            return

        existing_size = _extract_vector_size(info)
        existing_distance = _extract_vector_distance(info)
        if existing_size is not None and int(existing_size) != int(vector_size):
            raise ValueError(
                f"Qdrant collection {name} has vector size {existing_size}; expected {vector_size}."
            )
        if existing_distance is not None and existing_distance != qdrant_models.Distance.COSINE:
            raise ValueError(
                f"Qdrant collection {name} distance is {existing_distance}; expected cosine."
            )

    def upsert_points(self, points: Iterable[qdrant_models.PointStruct], *, wait: bool = True) -> int:
        if not self._collection_name:
            raise ValueError("Qdrant collection name is not set.")

        point_list = list(points)
        if not point_list:
            return 0

        self._client.upsert(collection_name=self._collection_name, points=point_list, wait=wait)
        return len(point_list)

    def ensure_payload_index(self, *, key: str, schema: qdrant_models.PayloadSchemaType) -> None:
        if not self._collection_name:
            raise ValueError("Qdrant collection name is not set.")
        try:
            self._client.create_payload_index(
                collection_name=self._collection_name,
                field_name=key,
                field_schema=schema,
                wait=True,
            )
        except Exception:
            logger.exception("Failed to ensure payload index key=%s collection=%s", key, self._collection_name)
            raise

    def search(
        self,
        *,
        vector: Sequence[float],
        limit: int,
        query_filter: Optional[qdrant_models.Filter] = None,
        with_payload: bool = True,
    ) -> list[qdrant_models.ScoredPoint]:
        if not self._collection_name:
            raise ValueError("Qdrant collection name is not set.")

        if hasattr(self._client, "search"):
            return self._client.search(
                collection_name=self._collection_name,
                query_vector=vector,
                limit=limit,
                query_filter=query_filter,
                with_payload=with_payload,
                with_vectors=False,
            )

        search_request = qdrant_models.SearchRequest(
            vector=vector,
            filter=query_filter,
            limit=limit,
            with_payload=with_payload,
            with_vector=False,
        )
        response = self._client.http.search_api.search_points(
            collection_name=self._collection_name,
            search_request=search_request,
        )
        return response.result or []

    def retrieve_payloads(self, ids: Sequence[str]) -> dict[str, dict]:
        if not self._collection_name:
            raise ValueError("Qdrant collection name is not set.")

        if not ids:
            return {}

        points = self._client.retrieve(
            collection_name=self._collection_name,
            ids=list(ids),
            with_payload=True,
            with_vectors=False,
        )
        payloads: dict[str, dict] = {}
        for point in points or []:
            payload = point.payload or {}
            payloads[str(point.id)] = dict(payload)
        return payloads


def build_payload_filter(
    *,
    kinds: Optional[Sequence[str]] = None,
    origin: Optional[str] = None,
    model_table_id: Optional[int] = None,
    source_table_name: Optional[str] = None,
    workspace_id: Optional[str] = None,
    workspace_table_ids: Optional[Sequence[int]] = None,
) -> Optional[qdrant_models.Filter]:
    must: list[qdrant_models.FieldCondition] = []

    if kinds:
        must.append(
            qdrant_models.FieldCondition(
                key="kind",
                match=qdrant_models.MatchAny(any=list(kinds)),
            )
        )

    if origin:
        must.append(
            qdrant_models.FieldCondition(
                key="origin",
                match=qdrant_models.MatchValue(value=origin),
            )
        )

    if model_table_id is not None:
        must.append(
            qdrant_models.FieldCondition(
                key="model_table_id",
                match=qdrant_models.MatchValue(value=int(model_table_id)),
            )
        )

    if source_table_name:
        must.append(
            qdrant_models.FieldCondition(
                key="source_table_name",
                match=qdrant_models.MatchValue(value=source_table_name),
            )
        )

    if workspace_id:
        must.append(
            qdrant_models.FieldCondition(
                key="workspace_id",
                match=qdrant_models.MatchValue(value=workspace_id),
            )
        )

    if workspace_table_ids:
        must.append(
            qdrant_models.FieldCondition(
                key="workspace_table_id",
                match=qdrant_models.MatchAny(any=[int(v) for v in workspace_table_ids]),
            )
        )

    if not must:
        return None

    return qdrant_models.Filter(must=must)


def _extract_vector_size(info: qdrant_models.CollectionInfo) -> Optional[int]:
    vectors = info.config.params.vectors
    if isinstance(vectors, qdrant_models.VectorParams):
        return int(vectors.size)
    if isinstance(vectors, dict):
        first = next(iter(vectors.values()), None)
        if isinstance(first, qdrant_models.VectorParams):
            return int(first.size)
    return None


def _extract_vector_distance(info: qdrant_models.CollectionInfo) -> Optional[qdrant_models.Distance]:
    vectors = info.config.params.vectors
    if isinstance(vectors, qdrant_models.VectorParams):
        return vectors.distance
    if isinstance(vectors, dict):
        first = next(iter(vectors.values()), None)
        if isinstance(first, qdrant_models.VectorParams):
            return first.distance
    return None
