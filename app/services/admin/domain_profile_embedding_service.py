from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.config import EMBEDDING_MODEL_NAME, QF_DOMAIN_PROFILE_LLM_MAX_TOKENS
from app.config.llm_resolver import build_llm_client_for_role
from app.constants.llm_roles import LLMRole
from app.exceptions.forge_error import ForgeError
from app.infra.embedding_model import EmbeddingModel
from app.models.domain.domain_profile import DomainProfileBase, compute_content_hash, _build_embedding_text
from app.ports.sql_executor import ForgeQueryPort
from app.services.admin.domain_profile_builder import DomainProfileBuilder
from app.services.llm.llm_client import LLMClient

logger = logging.getLogger(__name__)

_MAX_LLM_TOKENS = int(QF_DOMAIN_PROFILE_LLM_MAX_TOKENS)

_LIST_DOMAIN_IDS_QUERY = """
SELECT id
FROM domain
WHERE workspace_id = :workspace_id
  AND (:include_inactive = 1 OR is_active = 1)
ORDER BY id ASC
"""

_GET_EXISTING_PROFILE_QUERY = """
SELECT
  id,
  content_hash,
  embedding_model,
  embedded_at
FROM domain_profile
WHERE workspace_id = :workspace_id
  AND domain_id = :domain_id
LIMIT 1
"""

_UPSERT_PROFILE_QUERY = """
INSERT INTO domain_profile (
  workspace_id,
  domain_id,
  summary,
  keywords,
  entities,
  metrics,
  attributes,
  synonyms,
  acronyms,
  notes,
  embedding_text,
  content_hash,
  embedding_model,
  embedded_at
) VALUES (
  :workspace_id,
  :domain_id,
  :summary,
  :keywords,
  :entities,
  :metrics,
  :attributes,
  :synonyms,
  :acronyms,
  :notes,
  :embedding_text,
  :content_hash,
  :embedding_model,
  :embedded_at
)
ON DUPLICATE KEY UPDATE
  summary = VALUES(summary),
  keywords = VALUES(keywords),
  entities = VALUES(entities),
  metrics = VALUES(metrics),
  attributes = VALUES(attributes),
  synonyms = VALUES(synonyms),
  acronyms = VALUES(acronyms),
  notes = VALUES(notes),
  embedding_text = VALUES(embedding_text),
  content_hash = VALUES(content_hash),
  embedding_model = VALUES(embedding_model),
  embedded_at = VALUES(embedded_at),
  updated_at = CURRENT_TIMESTAMP
"""


class DomainProfileEmbeddingService:
    """Generates LLM-derived domain profile metadata for embedding/index pipelines."""

    def __init__(
        self,
        *,
        sql: Optional[ForgeQueryPort] = None,
        builder: Optional[DomainProfileBuilder] = None,
        llm_client: Optional[LLMClient] = None,
        embedding_model: Optional[EmbeddingModel] = None,
    ) -> None:
        self._sql = sql or ForgeMetaSQL()
        self._builder = builder or DomainProfileBuilder(sql=self._sql)
        self._explicit_llm = llm_client is not None
        self._llm = llm_client or LLMClient()
        self._embedding_model = embedding_model or EmbeddingModel(model_name=EMBEDDING_MODEL_NAME)
        self._llm_runtime_meta: Dict[str, Any] = {
            "source": "bootstrap",
            "role": LLMRole.ENRICHMENT,
            "llm_id": None,
            "provider": "generic",
            "model": str(getattr(self._llm, "_model", "") or ""),
            "endpoint": str(getattr(self._llm, "_endpoint", "") or ""),
        }

    def _resolve_runtime_llm(self, *, workspace_id: str, llm_id_override: Optional[int] = None) -> None:
        if self._explicit_llm:
            return
        resolved = build_llm_client_for_role(
            workspace_id=str(workspace_id or "").strip(),
            role=LLMRole.ENRICHMENT,
            llm_id_override=llm_id_override,
            timeout_seconds=None,
        )
        self._llm = resolved.client
        self._llm_runtime_meta = {
            "source": resolved.source,
            "role": resolved.role,
            "llm_id": resolved.llm_id,
            "provider": resolved.provider,
            "model": resolved.model,
            "endpoint": resolved.endpoint,
        }

    def generate_one(
        self,
        *,
        workspace_id: str,
        domain_id: int,
        force: bool = False,
        llm_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        return self._generate_domain(
            workspace_id=str(workspace_id or "").strip(),
            domain_id=int(domain_id),
            force=bool(force),
            llm_id=llm_id,
        )

    def generate_many(
        self,
        *,
        workspace_id: str,
        domain_ids: Sequence[int],
        force: bool = False,
        llm_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        workspace = str(workspace_id or "").strip()
        if not workspace:
            raise ForgeError("workspace_id is required", status_code=400)

        clean_ids = _normalize_domain_ids(domain_ids)
        if not clean_ids:
            raise ForgeError("domain_ids is required", status_code=400)

        results: List[Dict[str, Any]] = []
        failed = 0
        for domain_id in clean_ids:
            try:
                result = self._generate_domain(
                    workspace_id=workspace,
                    domain_id=domain_id,
                    force=bool(force),
                    llm_id=llm_id,
                )
                results.append(result)
            except ForgeError as exc:
                failed += 1
                trace_id = f"dpg_{uuid.uuid4().hex[:24]}"
                logger.exception(
                    "domain_profile_generate_failed workspace_id=%s domain_id=%s trace_id=%s",
                    workspace,
                    domain_id,
                    trace_id,
                )
                results.append(
                    {
                        "domain_id": int(domain_id),
                        "status": "failed",
                        "trace_id": trace_id,
                        "error": str(exc),
                    }
                )

        generated = sum(1 for row in results if row.get("status") == "generated")
        unchanged = sum(1 for row in results if row.get("status") == "unchanged")

        return {
            "workspace_id": workspace,
            "total": len(clean_ids),
            "generated": generated,
            "unchanged": unchanged,
            "failed": failed,
            "results": results,
        }

    def generate_all(
        self,
        *,
        workspace_id: str,
        force: bool = False,
        include_inactive: bool = False,
        llm_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        workspace = str(workspace_id or "").strip()
        if not workspace:
            raise ForgeError("workspace_id is required", status_code=400)
        rows = self._sql.execute_query_mappings(
            _LIST_DOMAIN_IDS_QUERY,
            {"workspace_id": workspace, "include_inactive": 1 if include_inactive else 0},
        )
        domain_ids = [int(row.get("id") or 0) for row in rows if int(row.get("id") or 0) > 0]
        return self.generate_many(
            workspace_id=workspace,
            domain_ids=domain_ids,
            force=force,
            llm_id=llm_id,
        )

    def _generate_domain(
        self,
        *,
        workspace_id: str,
        domain_id: int,
        force: bool,
        llm_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        if not workspace_id:
            raise ForgeError("workspace_id is required", status_code=400)
        if int(domain_id) <= 0:
            raise ForgeError("domain_id must be > 0", status_code=400)
        self._resolve_runtime_llm(workspace_id=workspace_id, llm_id_override=llm_id)

        started = time.perf_counter()
        trace_id = f"dpg_{uuid.uuid4().hex[:24]}"

        context = self._builder.build_domain_context(workspace_id=workspace_id, domain_id=int(domain_id))
        llm_payload, llm_meta = self._generate_profile_with_llm(context=context, trace_id=trace_id)

        embedding_text = str(llm_payload.get("embedding_text") or "").strip()
        if not embedding_text:
            fallback = DomainProfileBase(
                summary=str(llm_payload.get("summary") or "").strip() or None,
                keywords=_as_list(llm_payload.get("keywords")),
                entities=_as_list(llm_payload.get("entities")),
                metrics=_as_list(llm_payload.get("metrics")),
                attributes=_as_list(llm_payload.get("attributes")),
                synonyms=_as_list(llm_payload.get("synonyms")),
                acronyms=_as_list(llm_payload.get("acronyms")),
                notes=str(llm_payload.get("notes") or "").strip() or None,
            )
            embedding_text = _build_embedding_text(fallback)

        content_hash = compute_content_hash(embedding_text)
        existing = self._load_existing_profile(workspace_id=workspace_id, domain_id=int(domain_id))
        hash_changed = bool(force or not existing or existing.get("content_hash") != content_hash)

        embedding_generated = False
        embedding_model_name: Optional[str] = None
        embedded_at: Optional[datetime] = None

        if hash_changed:
            # Vector is generated to guarantee embedding_text is index-ready, then persisted via metadata fields.
            self._embedding_model.encode([embedding_text], normalize=True, batch_size=1)
            embedding_generated = True
            embedding_model_name = EMBEDDING_MODEL_NAME
            embedded_at = _utcnow_naive()
        else:
            embedding_model_name = _optional_text(existing.get("embedding_model") if existing else None)
            embedded_at = existing.get("embedded_at") if existing else None

        params = {
            "workspace_id": workspace_id,
            "domain_id": int(domain_id),
            "summary": _optional_text(llm_payload.get("summary")),
            "keywords": _json_or_none(_as_list(llm_payload.get("keywords"))),
            "entities": _json_or_none(_as_list(llm_payload.get("entities"))),
            "metrics": _json_or_none(_as_list(llm_payload.get("metrics"))),
            "attributes": _json_or_none(_as_list(llm_payload.get("attributes"))),
            "synonyms": _json_or_none(_as_list(llm_payload.get("synonyms"))),
            "acronyms": _json_or_none(_as_list(llm_payload.get("acronyms"))),
            "notes": _optional_text(llm_payload.get("notes")),
            "embedding_text": embedding_text,
            "content_hash": content_hash,
            "embedding_model": embedding_model_name,
            "embedded_at": embedded_at,
        }

        self._sql.execute_write(_UPSERT_PROFILE_QUERY, params)

        elapsed_ms = int((time.perf_counter() - started) * 1000)
        logger.info(
            "domain_profile_generate workspace_id=%s domain_id=%s trace_id=%s generation_time_ms=%s llm_tokens_used=%s hash_change=%s embedding_generated=%s",
            workspace_id,
            domain_id,
            trace_id,
            elapsed_ms,
            llm_meta.get("tokens") or {},
            hash_changed,
            embedding_generated,
        )

        return {
            "workspace_id": workspace_id,
            "domain_id": int(domain_id),
            "domain_name": (context.get("domain") or {}).get("name"),
            "status": "generated" if hash_changed else "unchanged",
            "trace_id": trace_id,
            "hash_changed": hash_changed,
            "embedding_generated": embedding_generated,
            "embedding_model": embedding_model_name,
            "generation_time_ms": elapsed_ms,
            "llm": llm_meta,
            "llm_resolution": dict(self._llm_runtime_meta),
        }

    def _generate_profile_with_llm(self, *, context: Mapping[str, Any], trace_id: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        system_prompt = _build_system_prompt()
        user_prompt = _build_user_prompt(context=context)

        attempt1 = self._llm.chat_json_with_trace(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_format=True,
            max_tokens=_MAX_LLM_TOKENS,
        )
        parsed, raw_text = _parse_llm_trace(attempt1)
        if parsed is None:
            repair_prompt = _build_repair_prompt(raw_text=raw_text)
            attempt2 = self._llm.chat_json_with_trace(
                system_prompt=system_prompt,
                user_prompt=repair_prompt,
                response_format=True,
                max_tokens=_MAX_LLM_TOKENS,
            )
            parsed, raw_text = _parse_llm_trace(attempt2)
            trace_for_usage = attempt2
        else:
            trace_for_usage = attempt1

        if parsed is None:
            raise ForgeError(
                "domain profile generation failed: invalid LLM JSON",
                status_code=502,
                details={
                    "trace_id": trace_id,
                    "llm_raw_json": str(raw_text or "")[:12000],
                },
            )

        normalized = _normalize_llm_payload(parsed)
        if not normalized.get("embedding_text"):
            normalized["embedding_text"] = _fallback_embedding_text_from_payload(normalized)

        model_name, tokens = _extract_model_and_tokens(trace_for_usage)
        meta = {
            "model": model_name,
            "tokens": tokens,
            "raw_json": str(raw_text or "")[:12000],
        }
        return normalized, meta

    def _load_existing_profile(self, *, workspace_id: str, domain_id: int) -> Optional[Dict[str, Any]]:
        rows = self._sql.execute_query_mappings(
            _GET_EXISTING_PROFILE_QUERY,
            {"workspace_id": workspace_id, "domain_id": int(domain_id)},
        )
        if not rows:
            return None
        return dict(rows[0])


def _build_system_prompt() -> str:
    return (
        "You are an expert data domain profiler for semantic retrieval.\n"
        "Return STRICT JSON only. No markdown. No comments. No prose outside JSON.\n"
        "Output must be one JSON object with keys:\n"
        "summary, keywords, entities, metrics, synonyms, acronyms, notes, embedding_text, attributes.\n"
        "Use arrays for keywords/entities/metrics/synonyms/acronyms/attributes.\n"
        "embedding_text must be long-form natural language optimized for semantic search and vector embeddings.\n"
        "It must include domain purpose, key entities, metrics, business concepts, synonyms, table relationships, and analytical use cases.\n"
        "Do not invent tables or columns not present in input context.\n"
    )


def _build_user_prompt(*, context: Mapping[str, Any]) -> str:
    compact_context = _compact_domain_context(context)
    return (
        "Analyze this complete domain definition and generate semantic profile JSON for embedding.\n"
        "This output will be used for semantic search vector embeddings. "
        "Optimize for discoverability and conceptual understanding.\n"
        "Prefer concise, information-dense output over exhaustive repetition.\n"
        f"domain_context_json: {json.dumps(compact_context, ensure_ascii=True)}"
    )


def _build_repair_prompt(*, raw_text: str) -> str:
    return (
        "Your previous output was not valid for the required JSON contract.\n"
        "Return JSON only with keys: "
        "summary, keywords, entities, metrics, synonyms, acronyms, notes, embedding_text, attributes.\n"
        f"Previous output: {str(raw_text or '')[:12000]}"
    )


def _parse_llm_trace(trace: Mapping[str, Any]) -> Tuple[Optional[Dict[str, Any]], str]:
    parsed = trace.get("parsed")
    raw_text = str(trace.get("content") or trace.get("raw_text") or "")

    if isinstance(parsed, Mapping):
        normalized = _extract_first_json_object(json.dumps(dict(parsed), ensure_ascii=True))
        if isinstance(normalized, dict):
            return normalized, raw_text

    from_raw = _extract_first_json_object(raw_text)
    if isinstance(from_raw, dict):
        return from_raw, raw_text

    return None, raw_text


def _extract_first_json_object(raw_text: str) -> Optional[Dict[str, Any]]:
    text = str(raw_text or "").strip()
    if not text:
        return None

    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except (TypeError, ValueError, json.JSONDecodeError):
        pass

    decoder = json.JSONDecoder()
    for idx, ch in enumerate(text):
        if ch != "{":
            continue
        try:
            obj, _ = decoder.raw_decode(text[idx:])
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if isinstance(obj, dict):
            return obj
    return None


def _normalize_llm_payload(payload: Mapping[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "summary": _optional_text(payload.get("summary")),
        "keywords": _as_list(payload.get("keywords")),
        "entities": _as_list(payload.get("entities")),
        "metrics": _as_list(payload.get("metrics")),
        "attributes": _as_list(payload.get("attributes")),
        "synonyms": _as_list(payload.get("synonyms")),
        "acronyms": _as_list(payload.get("acronyms")),
        "notes": _optional_text(payload.get("notes")),
        "embedding_text": _optional_text(payload.get("embedding_text")) or "",
    }
    return out


def _fallback_embedding_text_from_payload(payload: Mapping[str, Any]) -> str:
    profile = DomainProfileBase(
        summary=_optional_text(payload.get("summary")),
        keywords=_as_list(payload.get("keywords")),
        entities=_as_list(payload.get("entities")),
        metrics=_as_list(payload.get("metrics")),
        attributes=_as_list(payload.get("attributes")),
        synonyms=_as_list(payload.get("synonyms")),
        acronyms=_as_list(payload.get("acronyms")),
        notes=_optional_text(payload.get("notes")),
    )
    return _build_embedding_text(profile)


def _extract_model_and_tokens(trace: Mapping[str, Any]) -> Tuple[str, Dict[str, Any]]:
    model = "unknown"
    tokens: Dict[str, Any] = {}
    raw = str(trace.get("raw_text") or "").strip()
    if not raw:
        return model, tokens
    try:
        body = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return model, tokens
    if isinstance(body, dict):
        raw_model = body.get("model")
        if isinstance(raw_model, str) and raw_model.strip():
            model = raw_model.strip()
        usage = body.get("usage")
        if isinstance(usage, dict):
            tokens = usage
    return model, tokens


def _compact_domain_context(context: Mapping[str, Any]) -> Dict[str, Any]:
    tables = context.get("tables") if isinstance(context.get("tables"), list) else []
    joins = context.get("joins") if isinstance(context.get("joins"), list) else []
    relationship_lines = (
        context.get("relationship_lines")
        if isinstance(context.get("relationship_lines"), list)
        else []
    )
    stats = context.get("stats") if isinstance(context.get("stats"), Mapping) else {}
    domain = context.get("domain") if isinstance(context.get("domain"), Mapping) else {}

    max_tables = 12
    max_columns_per_table = 12
    max_joins = 12
    max_relationship_lines = 12

    compact_tables: List[Dict[str, Any]] = []
    omitted_columns = 0
    for raw_table in tables[:max_tables]:
        if not isinstance(raw_table, Mapping):
            continue
        raw_columns = raw_table.get("columns") if isinstance(raw_table.get("columns"), list) else []
        kept_columns = []
        for raw_column in raw_columns[:max_columns_per_table]:
            if not isinstance(raw_column, Mapping):
                continue
            kept_columns.append(
                {
                    "column_name": str(raw_column.get("column_name") or "").strip(),
                    "data_type": str(raw_column.get("data_type") or "").strip() or None,
                    "description": _truncate_text(raw_column.get("description"), 120),
                    "semantic_type": str(raw_column.get("semantic_type") or "").strip() or None,
                }
            )
        omitted_columns += max(0, len(raw_columns) - len(kept_columns))
        compact_tables.append(
            {
                "workspace_table_id": raw_table.get("workspace_table_id"),
                "table_name": str(raw_table.get("table_name") or "").strip(),
                "description": _truncate_text(raw_table.get("description"), 180),
                "is_primary": bool(raw_table.get("is_primary")),
                "table_alias": str(raw_table.get("table_alias") or "").strip() or None,
                "filter_mode": str(raw_table.get("filter_mode") or "").strip() or None,
                "cardinality": str(raw_table.get("cardinality") or "").strip() or None,
                "columns": kept_columns,
            }
        )

    compact_joins: List[Dict[str, Any]] = []
    for raw_join in joins[:max_joins]:
        if not isinstance(raw_join, Mapping):
            continue
        compact_joins.append(
            {
                "from_table_name": str(raw_join.get("from_table_name") or "").strip() or None,
                "to_table_name": str(raw_join.get("to_table_name") or "").strip() or None,
                "join_type": str(raw_join.get("join_type") or "").strip() or None,
                "join_spec": raw_join.get("join_spec") if isinstance(raw_join.get("join_spec"), Mapping) else {},
            }
        )

    return {
        "workspace_id": str(context.get("workspace_id") or "").strip(),
        "domain": {
            "domain_id": domain.get("domain_id"),
            "name": str(domain.get("name") or "").strip(),
            "description": _truncate_text(domain.get("description"), 220),
            "kind": str(domain.get("kind") or "").strip() or None,
            "is_active": bool(domain.get("is_active")),
        },
        "stats": {
            "table_count": int(stats.get("table_count") or len(tables)),
            "column_count": int(stats.get("column_count") or 0),
            "join_count": int(stats.get("join_count") or len(joins)),
            "tables_included_in_prompt": len(compact_tables),
            "tables_omitted_from_prompt": max(0, len(tables) - len(compact_tables)),
            "columns_omitted_from_prompt": omitted_columns,
            "joins_included_in_prompt": len(compact_joins),
            "joins_omitted_from_prompt": max(0, len(joins) - len(compact_joins)),
        },
        "tables": compact_tables,
        "joins": compact_joins,
        "relationship_lines": [
            _truncate_text(value, 180)
            for value in relationship_lines[:max_relationship_lines]
            if str(value or "").strip()
        ],
    }


def _truncate_text(value: Any, limit: int) -> Optional[str]:
    text = str(value or "").strip()
    if not text:
        return None
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def _json_or_none(value: Any) -> Optional[str]:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False)


def _as_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                return parsed
        except (TypeError, ValueError, json.JSONDecodeError):
            pass
        return [text]
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _optional_text(value: Any) -> Optional[str]:
    text = str(value or "").strip()
    return text or None


def _normalize_domain_ids(domain_ids: Sequence[int]) -> List[int]:
    out: List[int] = []
    seen: set[int] = set()
    for raw in list(domain_ids or []):
        try:
            domain_id = int(raw)
        except (TypeError, ValueError):
            continue
        if domain_id <= 0 or domain_id in seen:
            continue
        seen.add(domain_id)
        out.append(domain_id)
    return out


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


__all__ = ["DomainProfileEmbeddingService"]
