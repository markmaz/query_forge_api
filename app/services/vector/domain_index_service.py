from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence

from qdrant_client.http import models as qdrant_models

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.config import EMBEDDING_MODEL_NAME, QDRANT_DOMAIN_COLLECTION, QF_VERTICAL_DEFAULT
from app.exceptions.forge_error import ForgeError
from app.infra.embedding_model import EmbeddingModel
from app.infra.qdrant_client import QdrantClientWrapper
from app.ports.sql_executor import ForgeQueryPort

logger = logging.getLogger(__name__)

DEFAULT_COLLECTION = QDRANT_DOMAIN_COLLECTION or "domain_catalog_v1"
DEFAULT_VERTICAL = QF_VERTICAL_DEFAULT or "generic"
DEFAULT_LIMIT = 5
MAX_LIMIT = 50

_DOMAIN_PROFILE_QUERY = """
SELECT
  d.id AS domain_id,
  d.workspace_id,
  d.name,
  d.kind,
  d.is_active,
  dp.summary,
  dp.notes,
  dp.keywords,
  dp.entities,
  dp.metrics,
  dp.attributes,
  dp.embedding_text,
  COALESCE(UNIX_TIMESTAMP(dp.updated_at), UNIX_TIMESTAMP(dp.created_at), 0) AS domain_version,
  COUNT(DISTINCT dwt.workspace_table_id) AS table_count,
  SUM(CASE WHEN COALESCE(TRIM(dwt.relation_kind), '') <> '' THEN 1 ELSE 0 END) AS join_edge_count
FROM domain d
LEFT JOIN domain_profile dp
  ON dp.domain_id = d.id
 AND dp.workspace_id = d.workspace_id
LEFT JOIN domain_workspace_table dwt
  ON dwt.domain_id = d.id
WHERE (:workspace_id IS NULL OR d.workspace_id = :workspace_id)
GROUP BY
  d.id,
  d.workspace_id,
  d.name,
  d.kind,
  d.is_active,
  dp.summary,
  dp.notes,
  dp.keywords,
  dp.entities,
  dp.metrics,
  dp.attributes,
  dp.embedding_text,
  dp.updated_at,
  dp.created_at
ORDER BY d.id ASC
"""


@dataclass(frozen=True)
class DomainEmbeddingState:
    domain_id: int
    workspace_id: Optional[str]
    vertical_norm: str
    domain_version: int
    embedding_hash: str


class DomainVectorIndexService:
    def __init__(
        self,
        *,
        sql: Optional[ForgeQueryPort] = None,
        qdrant: Optional[QdrantClientWrapper] = None,
        model: Optional[EmbeddingModel] = None,
        collection_name: Optional[str] = None,
    ) -> None:
        self._sql = sql or ForgeMetaSQL()
        self._model = model or EmbeddingModel(model_name=EMBEDDING_MODEL_NAME)
        self._collection_name = collection_name or DEFAULT_COLLECTION
        self._qdrant = qdrant or QdrantClientWrapper(collection_name=self._collection_name)

    def ensure_collection(self) -> Dict[str, Any]:
        vector_size = int(getattr(self._model, "dimension", 0) or 0)
        if vector_size <= 0:
            vector_size = len(self._model.encode(["dimension probe"], normalize=True)[0])

        self._qdrant.ensure_collection(self._collection_name, vector_size)
        self._qdrant.ensure_payload_index(
            key="vertical_norm",
            schema=qdrant_models.PayloadSchemaType.KEYWORD,
        )
        self._qdrant.ensure_payload_index(
            key="is_active",
            schema=qdrant_models.PayloadSchemaType.BOOL,
        )
        self._qdrant.ensure_payload_index(
            key="domain_version",
            schema=qdrant_models.PayloadSchemaType.INTEGER,
        )
        self._qdrant.ensure_payload_index(
            key="workspace_id",
            schema=qdrant_models.PayloadSchemaType.KEYWORD,
        )
        return {
            "collection": self._collection_name,
            "vector_size": int(vector_size),
            "distance": "cosine",
            "payload_indexes": ["vertical_norm", "is_active", "domain_version", "workspace_id"],
        }

    def reindex_domains(
        self,
        *,
        workspace_id: Optional[str] = None,
        vertical_norm: Optional[str] = None,
        force: bool = False,
        json_fallback_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        t0 = time.perf_counter()
        vertical = _normalize_vertical(vertical_norm) if vertical_norm is not None else None
        rows = self._load_domains(workspace_id=workspace_id, json_fallback_path=json_fallback_path)
        if vertical is not None:
            rows = [row for row in rows if _infer_vertical_norm(row, default=DEFAULT_VERTICAL) == vertical]

        collection_meta = self.ensure_collection()
        state = self._load_embedding_state(workspace_id=workspace_id, vertical_norm=vertical)
        result = self.upsert_domains(
            rows,
            force=force,
            state_by_domain_id=state,
            vertical_norm=vertical,
        )
        result["timings_ms"] = {"total": int((time.perf_counter() - t0) * 1000)}
        result["collection"] = collection_meta
        logger.info("domain_vector_reindex completed result=%s", result)
        return result

    def upsert_domains(
        self,
        domains: Sequence[Mapping[str, Any]],
        *,
        force: bool = False,
        state_by_domain_id: Optional[Mapping[int, DomainEmbeddingState]] = None,
        vertical_norm: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not domains:
            return {"total": 0, "upserted": 0, "skipped": 0, "errors": []}

        t0 = time.perf_counter()
        state = dict(state_by_domain_id or {})
        points: List[qdrant_models.PointStruct] = []
        next_state: List[DomainEmbeddingState] = []
        skipped = 0
        errors: List[str] = []

        for row in domains:
            domain_id = _coerce_int(row.get("domain_id"), default=0)
            if domain_id <= 0:
                errors.append("domain_id_missing")
                continue

            embedding_text = build_domain_embedding_text(row)
            if embedding_text == "":
                skipped += 1
                continue

            inferred_vertical = _normalize_vertical(vertical_norm) if vertical_norm else _infer_vertical_norm(row, default=DEFAULT_VERTICAL)
            domain_version = _coerce_int(row.get("domain_version"), default=0)
            embedding_hash = hashlib.sha256(embedding_text.encode("utf-8")).hexdigest()
            ws_id = str(row.get("workspace_id") or "").strip() or None

            prev = state.get(domain_id)
            if (
                not force
                and prev is not None
                and prev.embedding_hash == embedding_hash
                and int(prev.domain_version) == int(domain_version)
                and prev.vertical_norm == inferred_vertical
            ):
                skipped += 1
                continue

            payload = {
                "domain_id": domain_id,
                "workspace_id": ws_id,
                "vertical_norm": inferred_vertical,
                "name": str(row.get("name") or "").strip(),
                "summary": str(row.get("summary") or "").strip(),
                "embedding_text": embedding_text,
                "domain_version": int(domain_version),
                "is_active": _coerce_bool(row.get("is_active"), default=True),
                "table_count": _coerce_int(row.get("table_count"), default=0),
                "join_edge_count": _coerce_int(row.get("join_edge_count"), default=0),
                "keywords": _as_text_list(row.get("keywords")),
            }
            points.append(qdrant_models.PointStruct(id=domain_id, vector=[], payload=payload))
            next_state.append(
                DomainEmbeddingState(
                    domain_id=domain_id,
                    workspace_id=ws_id,
                    vertical_norm=inferred_vertical,
                    domain_version=int(domain_version),
                    embedding_hash=embedding_hash,
                )
            )

        if points:
            vectors = self._model.encode([str(point.payload.get("embedding_text") or "") for point in points], normalize=True)
            for point, vector in zip(points, vectors, strict=True):
                point.vector = vector
            self._qdrant.upsert_points(points, wait=True)
            self._upsert_embedding_state(next_state)

        return {
            "total": len(domains),
            "upserted": len(points),
            "skipped": skipped,
            "errors": errors,
            "timings_ms": {"upsert": int((time.perf_counter() - t0) * 1000)},
        }

    def search_domains(
        self,
        *,
        workspace_id: str,
        query: str,
        vertical_norm: str,
        limit: int = DEFAULT_LIMIT,
        score_threshold: float = 0.2,
        include_payload: bool = True,
    ) -> Dict[str, Any]:
        query_text = _normalize_query_text(query)
        if query_text == "":
            raise ForgeError("query is required", status_code=400)

        ws = str(workspace_id or "").strip()
        if ws == "":
            raise ForgeError("workspace_id is required", status_code=400)

        k = max(1, min(int(limit or DEFAULT_LIMIT), MAX_LIMIT))
        vertical = _normalize_vertical(vertical_norm)
        threshold = float(score_threshold if score_threshold is not None else 0.2)

        vector = self._model.encode([query_text], normalize=True)[0]
        query_filter = qdrant_models.Filter(
            must=[
                qdrant_models.FieldCondition(
                    key="workspace_id",
                    match=qdrant_models.MatchValue(value=ws),
                ),
                qdrant_models.FieldCondition(
                    key="vertical_norm",
                    match=qdrant_models.MatchValue(value=vertical),
                ),
                qdrant_models.FieldCondition(
                    key="is_active",
                    match=qdrant_models.MatchValue(value=True),
                ),
            ]
        )

        hits = self._qdrant.search(
            vector=vector,
            limit=k,
            query_filter=query_filter,
            with_payload=True,
        )

        results: List[Dict[str, Any]] = []
        for hit in hits:
            score = float(hit.score or 0.0)
            if score < threshold:
                continue

            payload = dict(hit.payload or {})
            reasons = _overlap_reason_tokens(
                query_text,
                embedding_text=str(payload.get("embedding_text") or ""),
                keywords=_as_text_list(payload.get("keywords")),
                limit=5,
            )
            row = {
                "domain_id": _coerce_int(payload.get("domain_id"), default=_coerce_int(hit.id, default=0)),
                "name": str(payload.get("name") or "").strip(),
                "summary": str(payload.get("summary") or "").strip(),
                "score": round(score, 4),
                "reason": reasons,
                "domain_version": _coerce_int(payload.get("domain_version"), default=0),
                "table_count": _coerce_int(payload.get("table_count"), default=0),
                "join_edge_count": _coerce_int(payload.get("join_edge_count"), default=0),
            }
            if include_payload:
                row["payload"] = payload
            results.append(row)

        results.sort(key=lambda item: (-float(item.get("score") or 0.0), int(item.get("domain_id") or 0)))
        return {"results": results[:k]}

    def _load_domains(
        self,
        *,
        workspace_id: Optional[str],
        json_fallback_path: Optional[str],
    ) -> List[Dict[str, Any]]:
        ws = str(workspace_id or "").strip() or None
        try:
            rows = self._sql.execute_query_mappings(_DOMAIN_PROFILE_QUERY, {"workspace_id": ws})
        except Exception as exc:
            logger.warning("domain profile query failed; attempting fallback err=%s", exc)
            rows = []

        if rows:
            return [dict(row) for row in rows]

        if not json_fallback_path:
            return []

        try:
            with open(json_fallback_path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except Exception as exc:
            logger.warning("domain profile fallback load failed path=%s err=%s", json_fallback_path, exc)
            return []

        if isinstance(payload, list):
            rows = [dict(item) for item in payload if isinstance(item, dict)]
        elif isinstance(payload, dict):
            rows = [dict(item) for item in payload.get("domains", []) if isinstance(item, dict)]
        else:
            rows = []

        if ws:
            rows = [row for row in rows if str(row.get("workspace_id") or "").strip() == ws]
        return rows

    def _load_embedding_state(
        self,
        *,
        workspace_id: Optional[str],
        vertical_norm: Optional[str],
    ) -> Dict[int, DomainEmbeddingState]:
        ws = str(workspace_id or "").strip() or None
        vertical = _normalize_vertical(vertical_norm) if vertical_norm is not None else None

        where: List[str] = []
        params: Dict[str, Any] = {}
        if ws is not None:
            where.append("workspace_id = :workspace_id")
            params["workspace_id"] = ws
        if vertical is not None:
            where.append("vertical_norm = :vertical_norm")
            params["vertical_norm"] = vertical

        sql = """
        SELECT domain_id, workspace_id, vertical_norm, domain_version, embedding_hash
        FROM domain_embedding_state
        """
        if where:
            sql += " WHERE " + " AND ".join(where)

        try:
            rows = self._sql.execute_query_mappings(sql, params)
        except Exception as exc:
            if _is_missing_table_error(exc, "domain_embedding_state"):
                logger.warning("domain_embedding_state table missing; incremental mode disabled")
                return {}
            raise

        out: Dict[int, DomainEmbeddingState] = {}
        for row in rows:
            domain_id = _coerce_int(row.get("domain_id"), default=0)
            if domain_id <= 0:
                continue
            out[domain_id] = DomainEmbeddingState(
                domain_id=domain_id,
                workspace_id=str(row.get("workspace_id") or "").strip() or None,
                vertical_norm=_normalize_vertical(row.get("vertical_norm")),
                domain_version=_coerce_int(row.get("domain_version"), default=0),
                embedding_hash=str(row.get("embedding_hash") or "").strip(),
            )
        return out

    def _upsert_embedding_state(self, rows: Sequence[DomainEmbeddingState]) -> None:
        if not rows:
            return

        for row in rows:
            try:
                self._sql.execute_write(
                    """
                    INSERT INTO domain_embedding_state (
                      domain_id,
                      workspace_id,
                      vertical_norm,
                      domain_version,
                      embedding_hash,
                      indexed_at
                    ) VALUES (
                      :domain_id,
                      :workspace_id,
                      :vertical_norm,
                      :domain_version,
                      :embedding_hash,
                      UTC_TIMESTAMP()
                    )
                    ON DUPLICATE KEY UPDATE
                      workspace_id = VALUES(workspace_id),
                      vertical_norm = VALUES(vertical_norm),
                      domain_version = VALUES(domain_version),
                      embedding_hash = VALUES(embedding_hash),
                      indexed_at = UTC_TIMESTAMP()
                    """,
                    {
                        "domain_id": int(row.domain_id),
                        "workspace_id": row.workspace_id,
                        "vertical_norm": row.vertical_norm,
                        "domain_version": int(row.domain_version),
                        "embedding_hash": row.embedding_hash,
                    },
                )
            except Exception as exc:
                if _is_missing_table_error(exc, "domain_embedding_state"):
                    logger.warning("domain_embedding_state table missing; state write skipped")
                    return
                raise


def build_domain_embedding_text(domain_profile: Mapping[str, Any]) -> str:
    direct = str(domain_profile.get("embedding_text") or "").strip()
    if direct:
        return _collapse_ws(direct)

    name = str(domain_profile.get("name") or "").strip()
    summary = str(domain_profile.get("summary") or domain_profile.get("description") or "").strip()
    entities = _as_text_list(domain_profile.get("entities"))
    metrics = _as_text_list(domain_profile.get("metrics"))
    dimensions = _as_text_list(domain_profile.get("dimensions") or domain_profile.get("attributes"))
    keywords = _as_text_list(domain_profile.get("keywords"))
    questions = _as_text_list(
        domain_profile.get("questions")
        or domain_profile.get("questions_this_domain_answers")
        or domain_profile.get("example_questions")
    )

    sections: List[str] = []
    if name:
        sections.append(f"Domain: {name}")
    if summary:
        sections.append(f"Summary: {summary}")
    if entities:
        sections.append("Entities: " + ", ".join(entities))
    if metrics:
        sections.append("Metrics: " + ", ".join(metrics))
    if dimensions:
        sections.append("Key dimensions: " + ", ".join(dimensions))
    if keywords:
        sections.append("Keywords: " + ", ".join(keywords))
    if questions:
        sections.append("Questions this domain answers: " + "; ".join(questions))

    return _collapse_ws("\n".join(sections).strip())


def _normalize_query_text(text: Any) -> str:
    return _collapse_ws(str(text or "").strip())


def _normalize_vertical(value: Any) -> str:
    text = str(value or "").strip().lower()
    return text or DEFAULT_VERTICAL


def _infer_vertical_norm(row: Mapping[str, Any], *, default: str) -> str:
    explicit = str(row.get("vertical_norm") or row.get("vertical") or "").strip().lower()
    if explicit in {"education", "healthcare", "generic"}:
        return explicit

    blob_parts = [
        str(row.get("kind") or ""),
        str(row.get("name") or ""),
        str(row.get("summary") or ""),
        " ".join(_as_text_list(row.get("keywords"))),
    ]
    blob = " ".join(blob_parts).lower()
    edu_tokens = ("student", "school", "district", "attendance", "enrollment", "teacher", "k12")
    hc_tokens = ("patient", "provider", "claim", "diagnosis", "procedure", "npi", "health")
    if any(token in blob for token in edu_tokens):
        return "education"
    if any(token in blob for token in hc_tokens):
        return "healthcare"
    return _normalize_vertical(default)


def _as_text_list(value: Any) -> List[str]:
    parsed = value
    if isinstance(value, (bytes, bytearray, memoryview)):
        parsed = bytes(value).decode("utf-8", errors="ignore")
    if isinstance(parsed, str):
        text = parsed.strip()
        if text.startswith("[") and text.endswith("]"):
            try:
                parsed = json.loads(text)
            except Exception:
                parsed = [text]
        elif text == "":
            parsed = []
        else:
            parsed = [text]

    if isinstance(parsed, dict):
        parsed = list(parsed.values())
    if not isinstance(parsed, list):
        return []

    out: List[str] = []
    for item in parsed:
        if isinstance(item, str):
            v = _collapse_ws(item)
            if v:
                out.append(v)
        elif isinstance(item, dict):
            for val in item.values():
                vv = _collapse_ws(str(val or ""))
                if vv:
                    out.append(vv)
    return out


def _overlap_reason_tokens(
    query_text: str,
    *,
    embedding_text: str,
    keywords: Sequence[str],
    limit: int,
) -> List[str]:
    query_tokens = _tokenize(query_text)
    haystack_tokens = set(_tokenize(embedding_text))
    for keyword in keywords:
        haystack_tokens.update(_tokenize(keyword))

    reasons = [token for token in query_tokens if token in haystack_tokens]
    deduped: List[str] = []
    seen: set[str] = set()
    for token in reasons:
        if token in seen:
            continue
        seen.add(token)
        deduped.append(token)
        if len(deduped) >= max(1, int(limit)):
            break
    return deduped


def _tokenize(text: str) -> List[str]:
    return [token for token in re.findall(r"[a-z0-9]+", str(text or "").lower()) if len(token) > 1]


def _coerce_bool(value: Any, *, default: bool) -> bool:
    if value is None:
        return bool(default)
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "y", "on")
    return bool(default)


def _coerce_int(value: Any, *, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return int(default)


def _collapse_ws(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip())


def _is_missing_table_error(exc: Exception, table_name: str) -> bool:
    msg = str(exc).lower()
    table = table_name.lower()
    return (table in msg) and ("1146" in msg or "doesn't exist" in msg or "does not exist" in msg)


__all__ = [
    "DomainEmbeddingState",
    "DomainVectorIndexService",
    "build_domain_embedding_text",
]
