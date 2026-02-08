from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Sequence

from qdrant_client.http import models as qdrant_models

from app.adapters.mysql_sql_executor import MySQLSQLExecutor
from app.config import (
    QDRANT_COLUMN_COLLECTION,
    QDRANT_COLUMN_COLLECTION_V2,
    QDRANT_DOMAIN_COLLECTION,
    QDRANT_TABLE_COLLECTION,
)
from app.exceptions.service_error import ServiceError
from app.infra.embedding_model import EmbeddingModel
from app.infra.qdrant_client import QdrantClientWrapper, build_payload_filter
from app.ports.sql_executor import SQLExecutor
from app.services.embedding.domain_embedding_service import build_domain_point_id

logger = logging.getLogger(__name__)

TABLE_COLLECTION_NAME = QDRANT_TABLE_COLLECTION or "table_catalog"
COLUMN_COLLECTION_NAME = QDRANT_COLUMN_COLLECTION_V2 or QDRANT_COLUMN_COLLECTION or "column_catalog_v2"
DOMAIN_COLLECTION_NAME = QDRANT_DOMAIN_COLLECTION or "domain_catalog"
DEFAULT_LIMIT = 10
MAX_LIMIT = 50
ALLOWED_KINDS = {"table", "column", "domain"}


class EmbeddingSearchService:
    def __init__(
        self,
        *,
        table_qdrant: Optional[QdrantClientWrapper] = None,
        column_qdrant: Optional[QdrantClientWrapper] = None,
        domain_qdrant: Optional[QdrantClientWrapper] = None,
        sql: Optional[SQLExecutor] = None,
        model: Optional[EmbeddingModel] = None,
    ) -> None:
        self._table_qdrant = table_qdrant or QdrantClientWrapper(collection_name=TABLE_COLLECTION_NAME)
        self._column_qdrant = column_qdrant or QdrantClientWrapper(collection_name=COLUMN_COLLECTION_NAME)
        self._domain_qdrant = domain_qdrant or QdrantClientWrapper(collection_name=DOMAIN_COLLECTION_NAME)
        self._sql = sql or MySQLSQLExecutor()
        self._model = model or EmbeddingModel()

    def search(
        self,
        *,
        query: str,
        limit: Optional[int] = None,
        kinds: Optional[Sequence[str]] = None,
        workspace_id: Optional[str] = None,
        domain_id: Optional[int] = None,
        origin: Optional[str] = None,
        model_table_id: Optional[int] = None,
        source_table_name: Optional[str] = None,
        min_score: Optional[float] = None,
    ) -> Dict[str, Any]:
        query_text = (query or "").strip()
        if not query_text:
            raise ServiceError("query is required", status_code=400)

        limit_val = _clamp_limit(limit)
        kinds_list = _normalize_kinds(kinds)
        include_domain = "domain" in kinds_list
        include_table = "table" in kinds_list
        include_column = "column" in kinds_list

        origin_val = (origin or "").strip() or None
        source_table_val = (source_table_name or "").strip() or None

        query_vector = self._model.encode([query_text], normalize=True)[0]

        workspace_table_ids: Optional[List[int]] = None
        if domain_id is not None:
            if not workspace_id:
                raise ServiceError("workspace_id is required when domain_id is provided", status_code=400)
            workspace_table_ids = self._resolve_domain_workspace_table_ids(workspace_id, int(domain_id))

        scored: List[Dict[str, Any]] = []
        if include_table:
            payload_filter = build_payload_filter(
                kinds=["table"],
                origin=origin_val,
                model_table_id=model_table_id,
                source_table_name=source_table_val,
            )

            results = self._table_qdrant.search(
                vector=query_vector,
                limit=limit_val,
                query_filter=payload_filter,
                with_payload=True,
            )

            for hit in results:
                payload = hit.payload or {}
                kind = payload.get("kind")
                score = float(hit.score or 0.0)
                item: Dict[str, Any] = {
                    "kind": kind,
                    "score": score,
                    "modelTableId": payload.get("model_table_id"),
                    "sourceTableName": payload.get("source_table_name"),
                }
                if kind == "column":
                    item.update(
                        {
                            "modelColumnId": payload.get("model_column_id"),
                            "columnName": payload.get("column_name"),
                            "dataType": payload.get("data_type"),
                        }
                    )
                scored.append(item)

        if include_column:
            if domain_id is not None and not workspace_table_ids:
                logger.info(
                    "Embedding search: domain_id=%s has no workspace_table_ids; skipping column search",
                    domain_id,
                )
            else:
                column_filter = build_payload_filter(
                    kinds=["column"],
                    origin=origin_val,
                    workspace_id=workspace_id,
                    workspace_table_ids=workspace_table_ids,
                )
                column_results = self._column_qdrant.search(
                    vector=query_vector,
                    limit=limit_val,
                    query_filter=column_filter,
                    with_payload=True,
                )
                for hit in column_results:
                    payload = hit.payload or {}
                    score = float(hit.score or 0.0)
                    scored.append(
                        {
                            "kind": "column",
                            "score": score,
                            "workspaceId": payload.get("workspace_id"),
                            "workspaceTableId": payload.get("workspace_table_id"),
                            "workspaceColumnId": payload.get("workspace_column_id"),
                            "modelTableId": payload.get("model_table_id"),
                            "modelColumnId": payload.get("model_column_id"),
                            "tableName": payload.get("table_name"),
                            "columnName": payload.get("column_name"),
                            "dataType": payload.get("data_type"),
                        }
                    )

        if include_domain:
            domain_filter = _build_domain_filter(workspace_id)
            domain_results = self._domain_qdrant.search(
                vector=query_vector,
                limit=limit_val,
                query_filter=domain_filter,
                with_payload=True,
            )
            for hit in domain_results:
                payload = hit.payload or {}
                score = float(hit.score or 0.0)
                scored.append(
                    {
                        "kind": "domain",
                        "score": score,
                        "domainId": payload.get("domain_id"),
                        "domainName": payload.get("domain_name"),
                        "domainKind": payload.get("domain_kind"),
                        "workspaceId": payload.get("workspace_id"),
                    }
                )

        if min_score is not None:
            scored = [r for r in scored if float(r.get("score", 0.0)) >= float(min_score)]

        scored = _stable_sort_by_score(scored)
        scored = scored[:limit_val]

        logger.info(
            "Embedding search: query=%s limit=%s kinds=%s results=%s",
            query_text,
            limit_val,
            kinds_list,
            len(scored),
        )

        return {
            "query": query_text,
            "limit": limit_val,
            "results": scored,
        }

    def _resolve_domain_workspace_table_ids(self, workspace_id: str, domain_id: int) -> List[int]:
        point_id = build_domain_point_id(workspace_id, domain_id)
        payloads = self._domain_qdrant.retrieve_payloads([point_id])
        payload = payloads.get(point_id)
        if isinstance(payload, dict):
            ids = payload.get("workspace_table_ids")
            if isinstance(ids, list) and ids:
                return [int(v) for v in ids if v is not None]

        rows = self._sql.execute_query_mappings(
            """
            SELECT dwt.workspace_table_id
            FROM domain_workspace_table dwt
            JOIN domain d
              ON d.id = dwt.domain_id
            WHERE d.workspace_id = :workspace_id
              AND dwt.domain_id = :domain_id
            ORDER BY dwt.is_primary DESC, dwt.sort_order, dwt.workspace_table_id
            """,
            {"workspace_id": workspace_id, "domain_id": int(domain_id)},
        )
        return [int(r["workspace_table_id"]) for r in rows]


def _clamp_limit(limit: Optional[int]) -> int:
    try:
        parsed = int(limit) if limit is not None else DEFAULT_LIMIT
    except Exception:
        parsed = DEFAULT_LIMIT
    if parsed <= 0:
        parsed = DEFAULT_LIMIT
    return min(parsed, MAX_LIMIT)


def _normalize_kinds(kinds: Optional[Sequence[str]]) -> List[str]:
    if kinds is None:
        return ["column", "table", "domain"]

    if not isinstance(kinds, (list, tuple)):
        raise ServiceError("kinds must be an array", status_code=400)

    normalized = []
    for kind in kinds:
        if not isinstance(kind, str):
            raise ServiceError("kinds must be an array of strings", status_code=400)
        value = kind.strip().lower()
        if value:
            normalized.append(value)

    if not normalized:
        raise ServiceError("kinds cannot be empty", status_code=400)

    invalid = [k for k in normalized if k not in ALLOWED_KINDS]
    if invalid:
        raise ServiceError(f"invalid kinds: {', '.join(invalid)}", status_code=400)

    return list(dict.fromkeys(normalized))


def _stable_sort_by_score(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    indexed = list(enumerate(results))
    indexed.sort(key=lambda pair: (-float(pair[1].get("score", 0.0)), pair[0]))
    return [item for _, item in indexed]


def _build_domain_filter(workspace_id: Optional[str]) -> Optional[qdrant_models.Filter]:
    workspace = (workspace_id or "").strip()
    if not workspace:
        return None
    return qdrant_models.Filter(
        must=[
            qdrant_models.FieldCondition(
                key="workspace_id",
                match=qdrant_models.MatchValue(value=workspace),
            )
        ]
    )
