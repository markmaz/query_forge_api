from __future__ import annotations

import json
import logging
import uuid
from typing import Any, Dict, Iterable, List, Optional

from qdrant_client.http import models as qdrant_models

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.config import QDRANT_COLUMN_COLLECTION, QDRANT_COLUMN_COLLECTION_V2, QDRANT_TABLE_COLLECTION
from app.infra.embedding_model import DEFAULT_VECTOR_SIZE, EmbeddingModel
from app.infra.qdrant_client import QdrantClientWrapper
from app.ports.sql_executor import ForgeQueryPort

logger = logging.getLogger(__name__)

TABLE_COLLECTION_NAME = QDRANT_TABLE_COLLECTION or "table_catalog"
COLUMN_COLLECTION_NAME = QDRANT_COLUMN_COLLECTION_V2 or QDRANT_COLUMN_COLLECTION or "column_catalog_v2"
VECTOR_SIZE = DEFAULT_VECTOR_SIZE


class EmbeddingIndexService:
    def __init__(
        self,
        *,
        sql: Optional[ForgeQueryPort] = None,
        table_qdrant: Optional[QdrantClientWrapper] = None,
        column_qdrant: Optional[QdrantClientWrapper] = None,
        model: Optional[EmbeddingModel] = None,
    ) -> None:
        self._sql = sql or ForgeMetaSQL()
        self._table_qdrant = table_qdrant or QdrantClientWrapper(collection_name=TABLE_COLLECTION_NAME)
        self._column_qdrant = column_qdrant or QdrantClientWrapper(collection_name=COLUMN_COLLECTION_NAME)
        self._model = model or EmbeddingModel()

    def rebuild_index(
        self,
        *,
        include_tables: bool = True,
        limit: int = 0,
        workspace_id: Optional[str] = None,
    ) -> Dict[str, int]:
        limit_val = max(0, int(limit or 0))
        if include_tables:
            self._table_qdrant.ensure_collection(TABLE_COLLECTION_NAME, VECTOR_SIZE)
        self._column_qdrant.ensure_collection(COLUMN_COLLECTION_NAME, VECTOR_SIZE)

        tables = self._load_tables(limit_val) if include_tables else []
        columns = self._load_workspace_columns(workspace_id, limit_val)

        logger.info("Embedding rebuild start: tables=%s, columns=%s", len(tables), len(columns))

        tables_indexed = self._index_tables(tables)
        columns_indexed = self._index_columns(columns)

        logger.info(
            "Embedding rebuild complete: tablesIndexed=%s, columnsIndexed=%s",
            tables_indexed,
            columns_indexed,
        )

        return {"tablesIndexed": tables_indexed, "columnsIndexed": columns_indexed}

    def upsert_workspace_columns(self, workspace_id: str, *, limit: int = 0) -> Dict[str, Any]:
        workspace = (workspace_id or "").strip()
        if not workspace:
            raise ValueError("workspace_id is required")

        limit_val = max(0, int(limit or 0))
        self._column_qdrant.ensure_collection(COLUMN_COLLECTION_NAME, VECTOR_SIZE)
        columns = self._load_workspace_columns(workspace, limit_val)
        columns_indexed = self._index_columns(columns)
        return {"workspace_id": workspace, "columnsIndexed": columns_indexed}

    def _load_tables(self, limit: int) -> List[Dict[str, Any]]:
        sql = """
        SELECT
          id,
          source_table_name,
          description,
          origin
        FROM model_table
        WHERE is_missing_in_source = 0
        ORDER BY id
        """
        params: Dict[str, Any] = {}
        if limit > 0:
            sql += " LIMIT :limit"
            params["limit"] = limit

        rows = self._sql.execute_query_mappings(sql, params or None)
        return rows

    def _load_workspace_columns(
        self,
        workspace_id: Optional[str],
        limit: int,
    ) -> List[Dict[str, Any]]:
        sql = """
        SELECT
          wt.workspace_id,
          wt.id AS workspace_table_id,
          wc.id AS workspace_column_id,
          wt.model_table_id,
          mt.name AS model_table_name,
          mt.source_table_name,
          mt.origin AS model_origin,
          wt.table_name,
          wt.full_name,
          wc.column_name,
          wc.data_type AS workspace_data_type,
          mc.id AS model_column_id,
          mc.data_type AS model_data_type,
          mc.description AS column_description,
          mc.semantic_type AS semantic_type,
          mc.semantic_entity AS semantic_entity,
          mc.semantic_sub_type AS semantic_sub_type,
          mc.semantic_confidence AS semantic_confidence,
          mc.semantic_reasons_json AS semantic_reasons_json,
          mc.is_active AS model_is_active
        FROM workspace_table wt
        JOIN workspace_column wc ON wc.workspace_table_id = wt.id
        LEFT JOIN model_table mt ON mt.id = wt.model_table_id
        LEFT JOIN model_column mc
          ON mc.model_table_id = wt.model_table_id
         AND mc.column_name = wc.column_name
        WHERE wt.exists_in_dbx = 1
          AND wc.exists_in_dbx = 1
          AND (mt.is_missing_in_source = 0 OR mt.id IS NULL)
          AND (mc.is_missing_in_source = 0 OR mc.id IS NULL)
          AND (mc.is_active = 1 OR mc.id IS NULL)
        """
        params: Dict[str, Any] = {}
        if workspace_id:
            sql += " AND wt.workspace_id = :workspace_id"
            params["workspace_id"] = workspace_id

        sql += " ORDER BY wt.id, wc.id"

        if limit > 0:
            sql += " LIMIT :limit"
            params["limit"] = limit

        rows = self._sql.execute_query_mappings(sql, params or None)
        return rows

    def _index_tables(self, rows: List[Dict[str, Any]]) -> int:
        if not rows:
            return 0

        batch_size = 64
        total = 0
        for batch in _chunked(rows, batch_size):
            texts = [self._table_text(r) for r in batch]
            vectors = self._model.encode(texts, normalize=True, batch_size=batch_size)
            points = []
            for row, vector in zip(batch, vectors, strict=True):
                payload = {
                    "type": "table",
                    "kind": "table",
                    "model_table_id": int(row["id"]),
                    "source_table_name": row.get("source_table_name"),
                    "origin": row.get("origin"),
                    "external_id": f"t:{row['id']}",
                }
                points.append(
                    qdrant_models.PointStruct(
                        id=_deterministic_uuid("t", int(row["id"])),
                        vector=vector,
                        payload=payload,
                    )
                )

            upserted = self._table_qdrant.upsert_points(points)
            total += upserted
            logger.info("Upserted %s table embeddings", upserted)

        return total

    def _index_columns(self, rows: List[Dict[str, Any]]) -> int:
        if not rows:
            return 0

        batch_size = 64
        total = 0
        for batch in _chunked(rows, batch_size):
            texts = [self._column_text(r) for r in batch]
            vectors = self._model.encode(texts, normalize=True, batch_size=batch_size)
            points = []
            for row, vector in zip(batch, vectors, strict=True):
                payload = build_workspace_column_payload(row)
                points.append(
                    qdrant_models.PointStruct(
                        id=build_workspace_column_point_id(
                            row.get("workspace_id"),
                            row.get("workspace_column_id"),
                        ),
                        vector=vector,
                        payload=payload,
                    )
                )

            upserted = self._column_qdrant.upsert_points(points)
            total += upserted
            logger.info("Upserted %s column embeddings", upserted)

        return total

    @staticmethod
    def _table_text(row: Dict[str, Any]) -> str:
        source = (row.get("source_table_name") or "").strip()
        description = (row.get("description") or "").strip()
        return f"table: {source}\n description: {description}"

    @staticmethod
    def _column_text(row: Dict[str, Any]) -> str:
        workspace_id = (row.get("workspace_id") or "").strip()
        table_name = _resolve_table_name(row)
        column = (row.get("column_name") or "").strip()
        data_type = (row.get("model_data_type") or row.get("workspace_data_type") or "").strip()
        description = (row.get("column_description") or "").strip()
        semantic_type = (row.get("semantic_type") or "").strip()
        semantic_entity = (row.get("semantic_entity") or "").strip()
        semantic_sub_type = (row.get("semantic_sub_type") or "").strip()
        semantic_confidence = row.get("semantic_confidence")
        source_alias = (row.get("source_table_name") or "").strip()

        lines = [
            f"Workspace: {workspace_id}",
            f"Table: {table_name} (workspace_table_id={row.get('workspace_table_id')}, model_table_id={row.get('model_table_id')})",
            f"Column: {column} (workspace_column_id={row.get('workspace_column_id')}, model_column_id={row.get('model_column_id')})",
            f"Type: {data_type}",
            f"Description: {description}",
        ]
        if semantic_type:
            lines.append(f"Semantic type: {semantic_type}")
        if semantic_entity:
            lines.append(f"Semantic entity: {semantic_entity}")
        if semantic_sub_type:
            lines.append(f"Semantic sub-type: {semantic_sub_type}")
        if semantic_confidence is not None:
            lines.append(f"Semantic confidence: {semantic_confidence}")
        semantic_reasons = _parse_json_list(row.get("semantic_reasons_json"))
        if semantic_reasons:
            lines.append(f"Semantic reasoning: {', '.join(semantic_reasons[:5])}")
        if source_alias:
            lines.append(f"Also known as: {source_alias}")
        return "\n".join(lines)


def build_workspace_column_point_id(workspace_id: Any, workspace_column_id: Any) -> str:
    workspace = str(workspace_id or "").strip()
    if not workspace:
        raise ValueError("workspace_id is required")
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"col:{workspace}:{int(workspace_column_id)}"))


def build_workspace_column_payload(row: Dict[str, Any]) -> Dict[str, Any]:
    workspace_id = str(row.get("workspace_id") or "").strip()
    table_name = _resolve_table_name(row)
    data_type = (row.get("model_data_type") or row.get("workspace_data_type") or None)
    description = row.get("column_description") or None
    model_table_id = _to_int_or_none(row.get("model_table_id"))
    model_column_id = _to_int_or_none(row.get("model_column_id"))
    return {
        "type": "column",
        "kind": "column",
        "external_id": f"col:{workspace_id}:{int(row.get('workspace_column_id') or 0)}",
        "workspace_id": workspace_id,
        "workspace_table_id": int(row.get("workspace_table_id") or 0),
        "workspace_column_id": int(row.get("workspace_column_id") or 0),
        "model_table_id": model_table_id,
        "model_column_id": model_column_id,
        "table_name": table_name,
        "column_name": row.get("column_name"),
        "data_type": data_type,
        "description": description,
        "semantic_type": row.get("semantic_type"),
        "semantic_entity": row.get("semantic_entity"),
        "semantic_sub_type": row.get("semantic_sub_type"),
        "semantic_confidence": _to_float_or_none(row.get("semantic_confidence")),
        "semantic_reasons": _parse_json_list(row.get("semantic_reasons_json")),
        "origin": row.get("model_origin"),
        "is_active": _coerce_bool(row.get("model_is_active"), default=True),
    }


def _resolve_table_name(row: Dict[str, Any]) -> str:
    return (
        (row.get("model_table_name") or "")
        or (row.get("table_name") or "")
        or (row.get("full_name") or "")
    )


def _to_int_or_none(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except Exception:
        return None


def _to_float_or_none(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except Exception:
        return None


def _parse_json_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if not isinstance(value, str):
        return []
    text = value.strip()
    if text == "":
        return []
    try:
        parsed = json.loads(text)
    except Exception:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item).strip() for item in parsed if str(item).strip()]


def _coerce_bool(value: Any, *, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "y", "on")
    return default


def _chunked(items: Iterable[Dict[str, Any]], size: int) -> Iterable[List[Dict[str, Any]]]:
    chunk: List[Dict[str, Any]] = []
    for item in items:
        chunk.append(item)
        if len(chunk) >= size:
            yield chunk
            chunk = []
    if chunk:
        yield chunk


def _deterministic_uuid(prefix: str, numeric_id: int) -> uuid.UUID:
    return uuid.uuid5(uuid.NAMESPACE_URL, f"{prefix}:{numeric_id}")
