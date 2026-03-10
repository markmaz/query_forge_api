from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from qdrant_client.http import models as qdrant_models

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.config import QDRANT_DOMAIN_COLLECTION
from app.exceptions.forge_error import ForgeError
from app.infra.embedding_model import DEFAULT_VECTOR_SIZE, EmbeddingModel
from app.infra.qdrant_client import QdrantClientWrapper
from app.ports.sql_executor import ForgeQueryPort

logger = logging.getLogger(__name__)

COLLECTION_NAME = QDRANT_DOMAIN_COLLECTION or "domain_catalog"
VECTOR_SIZE = DEFAULT_VECTOR_SIZE
BATCH_SIZE = 64
ID_LOOKUP_BATCH = 256

DOMAIN_PROFILE_QUERY = """
SELECT
  dp.workspace_id,
  dp.domain_id,
  d.name AS domain_name,
  d.kind AS domain_kind,
  d.is_active AS domain_is_active,
  dp.summary,
  dp.keywords,
  dp.entities,
  dp.attributes,
  dp.metrics,
  dp.synonyms,
  dp.acronyms,
  dp.notes,
  dp.embedding_text,
  dp.content_hash,
  dp.updated_at
FROM domain_profile dp
JOIN domain d
  ON d.id = dp.domain_id
 AND d.workspace_id = dp.workspace_id
WHERE dp.workspace_id = :workspace_id
  AND d.is_active = 1;
"""


class DomainEmbeddingService:
    def __init__(
        self,
        *,
        sql: Optional[ForgeQueryPort] = None,
        qdrant: Optional[QdrantClientWrapper] = None,
        model: Optional[EmbeddingModel] = None,
    ) -> None:
        self._sql = sql or ForgeMetaSQL()
        self._qdrant = qdrant or QdrantClientWrapper(collection_name=COLLECTION_NAME)
        self._model = model or EmbeddingModel()

    def upsert_domain_profiles(self, workspace_id: str, *, force: bool = False) -> Dict[str, Any]:
        workspace = (workspace_id or "").strip()
        if not workspace:
            raise ForgeError("workspace_id is required", status_code=400)

        self._qdrant.ensure_collection(COLLECTION_NAME, VECTOR_SIZE)

        rows = self._load_domain_profiles(workspace)
        if not rows:
            return {"workspace_id": workspace, "upserted": 0, "skipped_empty": 0, "errors": []}

        existing_payloads = {} if force else self._load_existing_payloads(rows, workspace)
        domain_tables = self._load_domain_tables(workspace, rows)

        upserted = 0
        skipped_empty = 0
        skipped_unchanged = 0
        errors: List[str] = []

        for batch in _chunked(rows, BATCH_SIZE):
            texts: List[str] = []
            payloads: List[Dict[str, Any]] = []
            ids: List[str] = []

            for row in batch:
                embedding_text = _normalize_text(row.get("embedding_text"))
                if not embedding_text:
                    skipped_empty += 1
                    continue

                point_id = build_domain_point_id(workspace, row.get("domain_id"))
                content_hash = _normalize_text(row.get("content_hash"))
                table_rows = domain_tables.get(int(row.get("domain_id") or 0), [])
                workspace_table_ids = _extract_workspace_table_ids(table_rows)
                if not force and content_hash:
                    existing = existing_payloads.get(point_id, {})
                    if (
                        existing.get("content_hash") == content_hash
                        and _normalize_workspace_table_ids(existing.get("workspace_table_ids"))
                        == workspace_table_ids
                    ):
                        skipped_unchanged += 1
                        continue

                try:
                    payload = build_domain_payload(row, table_rows, workspace_table_ids)
                except Exception as exc:
                    domain_id = row.get("domain_id")
                    logger.exception("Failed to build payload for domain %s", domain_id)
                    errors.append(f"domain_id={domain_id}: {exc}")
                    continue

                ids.append(point_id)
                texts.append(embedding_text)
                payloads.append(payload)

            if not texts:
                continue

            vectors = self._model.encode(texts, normalize=True, batch_size=BATCH_SIZE)
            points = [
                qdrant_models.PointStruct(id=pid, vector=vector, payload=payload)
                for pid, vector, payload in zip(ids, vectors, payloads, strict=True)
            ]

            batch_upserted = self._qdrant.upsert_points(points)
            upserted += batch_upserted
            logger.info("Upserted %s domain profile embeddings", batch_upserted)

        result: Dict[str, Any] = {
            "workspace_id": workspace,
            "upserted": upserted,
            "skipped_empty": skipped_empty,
            "errors": errors,
        }
        if skipped_unchanged:
            result["skipped_unchanged"] = skipped_unchanged
        return result

    def _load_domain_profiles(self, workspace_id: str) -> List[Dict[str, Any]]:
        return self._sql.execute_query_mappings(DOMAIN_PROFILE_QUERY, {"workspace_id": workspace_id})

    def _load_existing_payloads(
        self,
        rows: Sequence[Mapping[str, Any]],
        workspace_id: str,
    ) -> Dict[str, Dict[str, Any]]:
        ids = []
        for row in rows:
            embedding_text = _normalize_text(row.get("embedding_text"))
            content_hash = _normalize_text(row.get("content_hash"))
            if not embedding_text or not content_hash:
                continue
            point_id = build_domain_point_id(workspace_id, row.get("domain_id"))
            ids.append(point_id)

        if not ids:
            return {}

        existing: Dict[str, Dict[str, Any]] = {}
        for batch in _chunked(ids, ID_LOOKUP_BATCH):
            payloads = self._qdrant.retrieve_payloads(batch)
            for point_id, payload in payloads.items():
                if isinstance(payload, dict):
                    existing[point_id] = dict(payload)

        return existing

    def _load_domain_tables(
        self,
        workspace_id: str,
        rows: Sequence[Mapping[str, Any]],
    ) -> Dict[int, List[Dict[str, Any]]]:
        domain_ids = sorted({int(r["domain_id"]) for r in rows if r.get("domain_id") is not None})
        if not domain_ids:
            return {}

        placeholders = ", ".join(f":id{i}" for i in range(len(domain_ids)))
        sql = f"""
        SELECT
          dwt.domain_id,
          dwt.workspace_table_id,
          dwt.role,
          dwt.is_primary,
          dwt.relation_kind,
          dwt.sort_order,
          dwt.table_alias,
          dwt.filter_mode,
          dwt.cardinality
        FROM domain_workspace_table dwt
        JOIN domain d
          ON d.id = dwt.domain_id
        WHERE d.workspace_id = :workspace_id
          AND dwt.domain_id IN ({placeholders})
        ORDER BY dwt.domain_id, dwt.is_primary DESC, dwt.sort_order, dwt.workspace_table_id
        """
        params = {"workspace_id": workspace_id}
        for idx, did in enumerate(domain_ids):
            params[f"id{idx}"] = did

        rows = self._sql.execute_query_mappings(sql, params)
        grouped: Dict[int, List[Dict[str, Any]]] = {}
        for row in rows:
            did = int(row.get("domain_id") or 0)
            grouped.setdefault(did, []).append(row)
        return grouped


def build_domain_point_id(workspace_id: str, domain_id: Any) -> str:
    workspace = (workspace_id or "").strip()
    if not workspace:
        raise ValueError("workspace_id is required")
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"domain:{workspace}:{int(domain_id)}"))


def build_domain_payload(
    row: Mapping[str, Any],
    table_rows: Sequence[Mapping[str, Any]],
    workspace_table_ids: Sequence[int],
) -> Dict[str, Any]:
    workspace_id = (row.get("workspace_id") or "").strip()
    domain_id = int(row.get("domain_id"))
    summary = _normalize_text(row.get("summary"))
    notes = _normalize_text(row.get("notes"))

    payload = {
        "type": "domain",
        "external_id": f"domain:{workspace_id}:{domain_id}",
        "workspace_id": workspace_id,
        "domain_id": domain_id,
        "domain_name": row.get("domain_name"),
        "domain_kind": row.get("domain_kind"),
        "is_active": _coerce_bool(row.get("domain_is_active")),
        "workspace_table_ids": list(workspace_table_ids),
        "workspace_tables": _format_workspace_tables(table_rows),
        "summary": summary,
        "keywords": _parse_json_list(row.get("keywords")),
        "entities": _parse_json_list(row.get("entities")),
        "attributes": _parse_json_list(row.get("attributes")),
        "metrics": _parse_json_list(row.get("metrics")),
        "synonyms": _parse_json_list(row.get("synonyms")),
        "acronyms": _parse_json_list(row.get("acronyms")),
        "notes": notes,
        "content_hash": _normalize_text(row.get("content_hash")),
        "updated_at": _format_timestamp(row.get("updated_at")),
    }
    return payload


def _parse_json_list(value: Any) -> List[Any]:
    parsed = _parse_json_value(value)
    if isinstance(parsed, list):
        return parsed
    if isinstance(parsed, dict):
        return [parsed]
    return []


def _parse_json_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (list, dict)):
        return value
    if isinstance(value, (bytes, bytearray, memoryview)):
        value = bytes(value).decode("utf-8", errors="ignore")
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return None
        try:
            return json.loads(raw)
        except Exception:
            return None
    return None


def _normalize_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (bytes, bytearray, memoryview)):
        value = bytes(value).decode("utf-8", errors="ignore")
    return str(value).strip()


def _format_timestamp(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    text = str(value).strip()
    return text or None


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "y", "on")
    return False


def _format_workspace_tables(rows: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    tables: List[Dict[str, Any]] = []
    for row in rows:
        tables.append(
            {
                "workspace_table_id": int(row.get("workspace_table_id") or 0),
                "is_primary": _coerce_bool(row.get("is_primary")),
                "role": _normalize_text(row.get("role")) or None,
                "relation_kind": _normalize_text(row.get("relation_kind")) or None,
                "sort_order": int(row.get("sort_order") or 0),
                "table_alias": _normalize_text(row.get("table_alias")) or None,
                "filter_mode": _normalize_text(row.get("filter_mode")) or None,
                "cardinality": _normalize_text(row.get("cardinality")) or None,
            }
        )
    return tables


def _extract_workspace_table_ids(rows: Sequence[Mapping[str, Any]]) -> List[int]:
    return [int(r.get("workspace_table_id")) for r in rows if r.get("workspace_table_id") is not None]


def _normalize_workspace_table_ids(value: Any) -> List[int]:
    if not value:
        return []
    if isinstance(value, list):
        return [int(v) for v in value if v is not None]
    return []


def _chunked(items: Sequence[Any] | Iterable[Any], size: int) -> Iterable[List[Any]]:
    chunk: List[Any] = []
    for item in items:
        chunk.append(item)
        if len(chunk) >= size:
            yield chunk
            chunk = []
    if chunk:
        yield chunk
