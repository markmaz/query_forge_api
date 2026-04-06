from __future__ import annotations

import json
import logging
import re
import uuid
from dataclasses import dataclass
from time import perf_counter
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from qdrant_client.http import models as qdrant_models
from sqlalchemy.exc import SQLAlchemyError

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.config.llm_resolver import build_llm_client_for_role
from app.constants.llm_roles import LLMRole
from app.exceptions.forge_error import ForgeError
from app.infra.embedding_model import EmbeddingModel
from app.infra.qdrant_client import QdrantClientWrapper
from app.models.query.ai_suggest import AddAggregateEdit, AddFilterEdit, AddGroupByEdit, AddSelectEdit, SetDomainEdit, SqlColumnKey
from app.ports.sql_executor import ForgeQueryPort
from app.services.llm.llm_client import LLMClient
from app.services.planner_llm.cache import PlannerLLMCache
from app.services.planner_llm.prompts import (
    PLAN_JSON_SCHEMA,
    build_developer_prompt,
    build_json_repair_prompt,
    build_system_prompt,
    build_user_prompt,
)
from app.services.planner_llm.validate import validate_and_repair
from app.services.sqljson_apply_service import apply_edits

logger = logging.getLogger(__name__)

SEMANTIC_COLLECTION = "semantic_concepts_v1"
COLUMN_COLLECTION = "column_catalog_v2"
DOMAIN_COLLECTION = "domain_catalog"


class PlannerLLMConstraints(BaseModel):
    model_config = ConfigDict(extra="ignore")

    max_domains: int = Field(default=3, ge=1, le=10)
    max_columns: int = Field(default=40, ge=5, le=120)
    max_concepts: int = Field(default=25, ge=5, le=100)
    allow_pii: bool = False


class PlannerLLMRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    workspace_id: str = Field(min_length=1)
    prompt: str = Field(min_length=1)
    vertical: str = Field(default="generic")
    constraints: PlannerLLMConstraints = Field(default_factory=PlannerLLMConstraints)
    debug: bool = False
    llm_id: Optional[int] = None


@dataclass
class LLMCallResult:
    parsed: Dict[str, Any]
    raw_content: str
    attempts: int
    repaired: bool


class PlannerLLMCandidateRetriever:
    def __init__(
        self,
        *,
        sql: Optional[ForgeQueryPort] = None,
        model: Optional[EmbeddingModel] = None,
        concept_qdrant: Optional[QdrantClientWrapper] = None,
        column_qdrant: Optional[QdrantClientWrapper] = None,
        domain_qdrant: Optional[QdrantClientWrapper] = None,
    ) -> None:
        self._sql = sql or ForgeMetaSQL()
        self._model = model or EmbeddingModel()
        self._concept_qdrant = concept_qdrant or QdrantClientWrapper(collection_name=SEMANTIC_COLLECTION)
        self._column_qdrant = column_qdrant or QdrantClientWrapper(collection_name=COLUMN_COLLECTION)
        self._domain_qdrant = domain_qdrant or QdrantClientWrapper(collection_name=DOMAIN_COLLECTION)

    def retrieve(
        self,
        *,
        workspace_id: str,
        vertical: str,
        normalized_prompt: str,
        constraints: PlannerLLMConstraints,
    ) -> Dict[str, Any]:
        vector = self._model.encode([normalized_prompt], normalize=True)[0]
        concept_candidates = self._search_concepts(vector=vector, vertical=vertical, limit=max(20, constraints.max_concepts * 4))
        domain_candidates = self._search_domains(vector=vector, workspace_id=workspace_id, limit=max(8, constraints.max_domains * 6))
        domain_tables = self._load_domain_tables(workspace_id=workspace_id, domain_ids=[d["domain_id"] for d in domain_candidates])
        allow_workspace_table_ids = sorted(
            {
                int(row.get("workspace_table_id"))
                for rows in domain_tables.values()
                for row in rows
                if _to_int(row.get("workspace_table_id")) is not None
            }
        )
        column_candidates = self._search_columns(
            vector=vector,
            workspace_id=workspace_id,
            allow_workspace_table_ids=allow_workspace_table_ids,
            limit=max(100, constraints.max_columns * 6),
            allow_pii=constraints.allow_pii,
            max_columns=constraints.max_columns,
        )
        ranked_domains = self._rank_domains(
            domain_candidates=domain_candidates,
            domain_tables=domain_tables,
            columns=column_candidates,
            max_domains=constraints.max_domains,
        )
        return {
            "domains": ranked_domains,
            "concepts": concept_candidates[: constraints.max_concepts],
            "columns": column_candidates,
        }

    def _search_concepts(self, *, vector: Sequence[float], vertical: str, limit: int) -> List[Dict[str, Any]]:
        vertical_norm = _norm_vertical(vertical)
        query_filter = qdrant_models.Filter(
            must=[
                qdrant_models.FieldCondition(key="type", match=qdrant_models.MatchAny(any=["concept", "alias"])),
                qdrant_models.FieldCondition(key="vertical_norm", match=qdrant_models.MatchAny(any=[vertical_norm, "generic"])),
            ]
        )
        hits = self._concept_qdrant.search(
            vector=vector,
            limit=limit,
            query_filter=query_filter,
            with_payload=True,
        )
        by_key: Dict[str, Dict[str, Any]] = {}
        for hit in hits:
            payload = hit.payload or {}
            concept_key = str(payload.get("concept_key") or "").strip().upper()
            if concept_key == "":
                continue
            row = by_key.get(concept_key)
            score = float(hit.score or 0.0)
            alias = str(payload.get("alias_key") or "").strip()
            if row is None:
                row = {
                    "id": _to_int(payload.get("concept_id")),
                    "concept_key": concept_key,
                    "name": str(payload.get("name") or concept_key),
                    "semantic_type": str(payload.get("semantic_type") or "unknown"),
                    "aliases_top3": [],
                    "_score": score,
                }
                by_key[concept_key] = row
            else:
                row["_score"] = max(float(row.get("_score") or 0.0), score)
            if alias and alias not in row["aliases_top3"] and len(row["aliases_top3"]) < 3:
                row["aliases_top3"].append(alias)
        rows = list(by_key.values())
        rows.sort(key=lambda item: -float(item.get("_score") or 0.0))
        for row in rows:
            row.pop("_score", None)
        return rows

    def _search_domains(self, *, vector: Sequence[float], workspace_id: str, limit: int) -> List[Dict[str, Any]]:
        query_filter = qdrant_models.Filter(
            must=[
                qdrant_models.FieldCondition(key="type", match=qdrant_models.MatchValue(value="domain")),
                qdrant_models.FieldCondition(key="workspace_id", match=qdrant_models.MatchValue(value=str(workspace_id))),
            ]
        )
        hits = self._domain_qdrant.search(
            vector=vector,
            limit=limit,
            query_filter=query_filter,
            with_payload=True,
        )
        out: List[Dict[str, Any]] = []
        for hit in hits:
            payload = hit.payload or {}
            did = _to_int(payload.get("domain_id"))
            if did is None:
                continue
            out.append(
                {
                    "domain_id": did,
                    "name": str(payload.get("domain_name") or f"domain_{did}"),
                    "raw_score": float(hit.score or 0.0),
                    "workspace_tables": list(payload.get("workspace_tables") or []),
                }
            )
        return out

    def _load_domain_tables(self, *, workspace_id: str, domain_ids: Sequence[int]) -> Dict[int, List[Dict[str, Any]]]:
        clean_ids = sorted({int(item) for item in domain_ids if _to_int(item) is not None})
        if not clean_ids:
            return {}
        in_sql, params = _in_clause("did", clean_ids)
        rows = self._sql.execute_query_mappings(
            f"""
            SELECT
              dwt.domain_id,
              dwt.workspace_table_id,
              wt.table_name,
              dwt.relation_kind
            FROM domain_workspace_table dwt
            JOIN workspace_table wt
              ON wt.id = dwt.workspace_table_id
             AND wt.workspace_id = :workspace_id
            WHERE dwt.domain_id IN ({in_sql})
            ORDER BY dwt.domain_id, dwt.workspace_table_id
            """,
            {"workspace_id": str(workspace_id), **params},
        )
        grouped: Dict[int, List[Dict[str, Any]]] = {}
        for row in rows:
            did = _to_int(row.get("domain_id"))
            if did is None:
                continue
            grouped.setdefault(did, []).append(dict(row))
        return grouped

    def _search_columns(
        self,
        *,
        vector: Sequence[float],
        workspace_id: str,
        allow_workspace_table_ids: Sequence[int],
        limit: int,
        allow_pii: bool,
        max_columns: int,
    ) -> List[Dict[str, Any]]:
        must: List[qdrant_models.FieldCondition] = [
            qdrant_models.FieldCondition(key="kind", match=qdrant_models.MatchValue(value="column")),
            qdrant_models.FieldCondition(key="workspace_id", match=qdrant_models.MatchValue(value=str(workspace_id))),
        ]
        if allow_workspace_table_ids:
            must.append(
                qdrant_models.FieldCondition(
                    key="workspace_table_id",
                    match=qdrant_models.MatchAny(any=[int(item) for item in allow_workspace_table_ids]),
                )
            )
        query_filter = qdrant_models.Filter(must=must)
        hits = self._column_qdrant.search(
            vector=vector,
            limit=limit,
            query_filter=query_filter,
            with_payload=True,
        )
        raw_rows: List[Dict[str, Any]] = []
        for hit in hits:
            payload = hit.payload or {}
            wtid = _to_int(payload.get("workspace_table_id"))
            col_name = str(payload.get("column_name") or "").strip()
            if wtid is None or col_name == "":
                continue
            semantic = str(payload.get("semantic_type") or "").strip().lower() or "unknown"
            pii_flag = _is_pii_column(column_name=col_name, semantic_type=semantic)
            if pii_flag and not allow_pii:
                continue
            raw_rows.append(
                {
                    "column_key": _column_key(wtid, col_name),
                    "workspace_table_id": wtid,
                    "model_column_id": _to_int(payload.get("model_column_id")),
                    "column_name": col_name,
                    "table": str(payload.get("table_name") or ""),
                    "data_type": str(payload.get("data_type") or "unknown"),
                    "semantic_type_strict": semantic,
                    "sample_values": [],
                    "pii_flag": pii_flag,
                    "_score": float(hit.score or 0.0),
                }
            )
        shaped = self._shape_columns_with_per_table_cap(rows=raw_rows, max_columns=max_columns, per_table_cap=8)
        sample_map = self._load_sample_values_for_model_columns(model_column_ids=[row.get("model_column_id") for row in shaped])
        for row in shaped:
            mid = _to_int(row.get("model_column_id"))
            row["sample_values"] = list(sample_map.get(mid, []))[:3] if mid is not None else []
            row.pop("_score", None)
        return shaped

    @staticmethod
    def _shape_columns_with_per_table_cap(
        *,
        rows: Sequence[Dict[str, Any]],
        max_columns: int,
        per_table_cap: int,
    ) -> List[Dict[str, Any]]:
        table_counts: Dict[str, int] = {}
        out: List[Dict[str, Any]] = []
        seen_keys: set[str] = set()
        sorted_rows = sorted(rows, key=lambda item: -float(item.get("_score") or 0.0))
        for row in sorted_rows:
            key = str(row.get("column_key") or "").strip().lower()
            if key == "" or key in seen_keys:
                continue
            table = str(row.get("table") or "").strip().lower() or "unknown"
            count = table_counts.get(table, 0)
            if count >= per_table_cap:
                continue
            out.append(dict(row))
            seen_keys.add(key)
            table_counts[table] = count + 1
            if len(out) >= max_columns:
                break
        return out

    def _rank_domains(
        self,
        *,
        domain_candidates: Sequence[Dict[str, Any]],
        domain_tables: Mapping[int, Sequence[Dict[str, Any]]],
        columns: Sequence[Dict[str, Any]],
        max_domains: int,
    ) -> List[Dict[str, Any]]:
        covered_tables = {str(row.get("table") or "").strip().lower() for row in columns if str(row.get("table") or "").strip()}
        ranked: List[Dict[str, Any]] = []
        for domain in domain_candidates:
            did = _to_int(domain.get("domain_id"))
            if did is None:
                continue
            rows = list(domain_tables.get(did) or [])
            tables = [str(item.get("table_name") or "").strip() for item in rows if str(item.get("table_name") or "").strip()]
            table_keys = {t.lower() for t in tables}
            coverage = (len(table_keys & covered_tables) / float(len(table_keys))) if table_keys else 0.0
            joinable_edges = sum(1 for row in rows if str(row.get("relation_kind") or "").strip())
            joinability = (joinable_edges / float(len(rows))) if rows else 0.0
            raw_score = float(domain.get("raw_score") or 0.0)
            final_score = (raw_score * 0.6) + (coverage * 0.3) + (joinability * 0.1)
            ranked.append(
                {
                    "domain_id": did,
                    "name": str(domain.get("name") or f"domain_{did}"),
                    "tables": tables,
                    "join_summary": {
                        "table_count": len(rows),
                        "joinable_edges": joinable_edges,
                    },
                    "_score": final_score,
                }
            )
        ranked.sort(key=lambda item: -float(item.get("_score") or 0.0))
        out = ranked[: max_domains]
        for row in out:
            row.pop("_score", None)
        return out

    def _load_sample_values_for_model_columns(self, *, model_column_ids: Sequence[Any]) -> Dict[int, List[Any]]:
        mids = sorted({int(mid) for mid in model_column_ids if _to_int(mid) is not None})
        if not mids:
            return {}
        in_sql, params = _in_clause("mid", mids)
        rows = self._sql.execute_query_mappings(
            f"""
            SELECT id, sample_values_json
            FROM workspace_column
            WHERE id IN ({in_sql})
            """,
            params,
        )
        out: Dict[int, List[Any]] = {}
        for row in rows:
            mid = _to_int(row.get("id"))
            if mid is None:
                continue
            sample_raw = row.get("sample_values_json")
            samples = _parse_json_list(sample_raw)[:3]
            out[mid] = samples
        return out


class PlannerLLMService:
    def __init__(
        self,
        *,
        sql: Optional[ForgeQueryPort] = None,
        llm_client: Optional[LLMClient] = None,
        cache: Optional[PlannerLLMCache] = None,
        retriever: Optional[PlannerLLMCandidateRetriever] = None,
    ) -> None:
        self._sql = sql or ForgeMetaSQL()
        self._explicit_llm = llm_client is not None
        self._llm = llm_client or LLMClient(timeout_seconds=60)
        self._cache = cache or PlannerLLMCache(sql=self._sql)
        self._retriever = retriever or PlannerLLMCandidateRetriever(sql=self._sql)
        self._llm_runtime_meta: Dict[str, Any] = {
            "source": "bootstrap",
            "role": LLMRole.PLANNER,
            "llm_id": None,
            "provider": "generic",
            "model": str(getattr(self._llm, "_model", "") or ""),
            "endpoint": str(getattr(self._llm, "_endpoint", "") or ""),
        }

    def _resolve_runtime_llm(self, *, workspace_id: str, llm_id_override: Optional[int] = None) -> None:
        if self._explicit_llm:
            return
        resolved = build_llm_client_for_role(
            workspace_id=workspace_id,
            role=LLMRole.PLANNER,
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

    def plan(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        try:
            req = PlannerLLMRequest.model_validate(payload or {})
        except ValidationError as exc:
            raise ForgeError("Invalid planner_llm request", status_code=400, details={"errors": exc.errors()}) from exc
        self._resolve_runtime_llm(workspace_id=req.workspace_id, llm_id_override=req.llm_id)

        trace_id = str(uuid.uuid4())
        timings: Dict[str, int] = {}
        t0 = perf_counter()

        normalized_prompt = normalize_prompt_for_planner(req.prompt)
        vertical = _norm_vertical(req.vertical)
        registry_version = self._cache.get_registry_version(vertical=vertical)
        cache_key = self._cache.build_cache_key(
            workspace_id=req.workspace_id,
            vertical=vertical,
            normalized_prompt=normalized_prompt,
            constraints=req.constraints.model_dump(mode="json"),
            registry_version=registry_version,
        )

        t_cache = perf_counter()
        cached = self._cache.get(cache_key=cache_key, registry_version=registry_version)
        timings["cache_lookup"] = _elapsed_ms(t_cache)
        if cached:
            response = {
                "plan_json": cached.get("plan_json") or {},
                "sql_json": cached.get("sql_json") or {},
                "validation": cached.get("validation") or {"is_valid": False, "errors": ["invalid_cache"], "repairs_applied": []},
                "candidates": cached.get("candidates") or {"domains": [], "concepts": [], "columns": []},
                "trace_id": trace_id,
                "timings_ms": {**timings, "total": _elapsed_ms(t0)},
                "cache": {"hit": True, "key": cache_key},
            }
            if req.debug:
                response["debug_artifacts"] = {
                    "normalized_prompt": normalized_prompt,
                    "registry_version": registry_version,
                    "llm_resolution": dict(self._llm_runtime_meta),
                }
            logger.info(
                "planner_llm trace_id=%s cache_hit=true workspace_id=%s vertical=%s timings_ms=%s",
                trace_id,
                req.workspace_id,
                vertical,
                response["timings_ms"],
            )
            return response

        t_candidates = perf_counter()
        candidates = self._retriever.retrieve(
            workspace_id=req.workspace_id,
            vertical=vertical,
            normalized_prompt=normalized_prompt,
            constraints=req.constraints,
        )
        timings["candidate_retrieval"] = _elapsed_ms(t_candidates)

        t_llm = perf_counter()
        llm_result = self.call_llm_json(
            normalized_prompt=normalized_prompt,
            candidates=candidates,
            schema=PLAN_JSON_SCHEMA,
            temperature=0.1,
        )
        timings["llm_plan"] = _elapsed_ms(t_llm)

        t_validate = perf_counter()
        validated = validate_and_repair(
            plan_json=llm_result.parsed,
            candidates=candidates,
            normalized_prompt=normalized_prompt,
            allow_pii=req.constraints.allow_pii,
            group_by_cap=8,
            max_domains=req.constraints.max_domains,
        )
        validation_payload = {
            "is_valid": validated.is_valid,
            "errors": validated.errors,
            "repairs_applied": validated.repairs_applied,
        }
        timings["validation"] = _elapsed_ms(t_validate)

        t_compile = perf_counter()
        sql_json = self._compile_plan_to_sql_json(
            plan_json=validated.plan_json,
            candidates=candidates,
            prompt=req.prompt,
        ) if validated.is_valid else {}
        timings["compile"] = _elapsed_ms(t_compile)

        t_cache_write = perf_counter()
        try:
            self._cache.set(
                cache_key=cache_key,
                workspace_id=req.workspace_id,
                vertical=vertical,
                normalized_prompt=normalized_prompt,
                constraints=req.constraints.model_dump(mode="json"),
                registry_version=registry_version,
                plan_json=validated.plan_json,
                sql_json=sql_json,
                validation=validation_payload,
                candidates={k: list(v) for k, v in candidates.items() if k in {"domains", "concepts", "columns"}},
            )
        except (OSError, RuntimeError, TypeError, ValueError, SQLAlchemyError):
            logger.exception("planner_llm cache write failed trace_id=%s", trace_id)
        timings["cache_write"] = _elapsed_ms(t_cache_write)

        response = {
            "plan_json": validated.plan_json,
            "sql_json": sql_json,
            "validation": validation_payload,
            "candidates": {
                "domains": list(candidates.get("domains") or []),
                "concepts": list(candidates.get("concepts") or []),
                "columns": list(candidates.get("columns") or []),
            },
            "trace_id": trace_id,
            "timings_ms": {**timings, "total": _elapsed_ms(t0)},
            "cache": {"hit": False, "key": cache_key},
        }
        if req.debug:
            response["debug_artifacts"] = {
                "normalized_prompt": normalized_prompt,
                "llm_raw_json": llm_result.raw_content,
                "llm_attempts": llm_result.attempts,
                "llm_repaired": llm_result.repaired,
                "registry_version": registry_version,
                "repairs": validation_payload["repairs_applied"],
                "llm_resolution": dict(self._llm_runtime_meta),
            }
        logger.info(
            "planner_llm trace_id=%s cache_hit=false workspace_id=%s vertical=%s valid=%s timings_ms=%s",
            trace_id,
            req.workspace_id,
            vertical,
            validation_payload["is_valid"],
            response["timings_ms"],
        )
        return response

    def call_llm_json(
        self,
        *,
        normalized_prompt: str,
        candidates: Dict[str, Sequence[Dict[str, Any]]],
        schema: Dict[str, Any],
        temperature: float = 0.1,
    ) -> LLMCallResult:
        del temperature  # temperature is fixed in LLMClient adapter for now
        system_prompt = build_system_prompt()
        developer_prompt = build_developer_prompt(schema)
        user_prompt = build_user_prompt(
            normalized_prompt=normalized_prompt,
            candidates=candidates,
            schema=schema,
        )
        composed_user = f"{developer_prompt}\n\n{user_prompt}"

        attempts = 0
        last_raw = ""
        for _ in range(2):
            attempts += 1
            trace = self._llm.chat_json_with_trace(
                system_prompt=system_prompt,
                user_prompt=composed_user,
                response_format=True,
                max_tokens=1600,
            )
            parsed = trace.get("parsed") if isinstance(trace.get("parsed"), dict) else None
            raw_content = str(trace.get("content") or trace.get("raw_text") or "")
            last_raw = raw_content
            if parsed is not None and _looks_like_plan_json(parsed):
                return LLMCallResult(parsed=parsed, raw_content=raw_content, attempts=attempts, repaired=False)

        repair_prompt = build_json_repair_prompt(schema=schema, broken_json=last_raw)
        repair_trace = self._llm.chat_json_with_trace(
            system_prompt=system_prompt,
            user_prompt=repair_prompt,
            response_format=True,
            max_tokens=1800,
        )
        parsed = repair_trace.get("parsed") if isinstance(repair_trace.get("parsed"), dict) else None
        raw_content = str(repair_trace.get("content") or repair_trace.get("raw_text") or "")
        if parsed is not None and _looks_like_plan_json(parsed):
            return LLMCallResult(parsed=parsed, raw_content=raw_content, attempts=3, repaired=True)
        raise ForgeError("planner_llm invalid model JSON", status_code=502, details={"raw": raw_content[:2000]})

    def _compile_plan_to_sql_json(
        self,
        *,
        plan_json: Dict[str, Any],
        candidates: Mapping[str, Sequence[Dict[str, Any]]],
        prompt: str,
    ) -> Dict[str, Any]:
        column_lookup = {
            str(row.get("column_key") or "").strip().lower(): dict(row)
            for row in list(candidates.get("columns") or [])
            if isinstance(row, dict) and str(row.get("column_key") or "").strip()
        }
        derived_lookup = {
            str(row.get("name") or "").strip().lower(): dict(row)
            for row in list(plan_json.get("derived_metrics") or [])
            if isinstance(row, dict) and str(row.get("name") or "").strip()
        }
        edits: List[Any] = []
        derived_agg_metrics: List[Dict[str, Any]] = []
        domains = [item for item in list(plan_json.get("domains") or []) if _to_int(item) is not None]
        if domains:
            edits.append(SetDomainEdit(op="setDomain", domainId=int(domains[0])))

        for item in list((plan_json.get("selects") or {}).get("dimensions") or []):
            key = str(item.get("column_key") or "").strip().lower()
            row = column_lookup.get(key)
            col = _to_sql_column_key(row)
            if col is None:
                continue
            edits.append(AddSelectEdit(op="addSelect", col=col, alias=item.get("label")))

        for item in list((plan_json.get("selects") or {}).get("metrics") or []):
            ref_kind, ref_value = _split_metric_ref(item.get("metric_ref"), fallback_column_key=item.get("column_key"))
            if ref_kind != "column":
                continue
            row = column_lookup.get(ref_value)
            col = _to_sql_column_key(row)
            if col is None:
                continue
            # list intent may project metric columns directly
            if str(plan_json.get("intent") or "").strip().lower() == "list":
                edits.append(AddSelectEdit(op="addSelect", col=col, alias=item.get("label")))

        for item in list(plan_json.get("filters") or []):
            key = str(item.get("column_key") or "").strip().lower()
            row = column_lookup.get(key)
            col = _to_sql_column_key(row)
            if col is None:
                continue
            op = _to_filter_operator(item.get("op"))
            if op is None:
                continue
            edits.append(
                AddFilterEdit(
                    op="addFilter",
                    col=col,
                    operator=op,
                    value=_filter_value_for_operator(item=item, operator=op),
                )
            )

        for key in list((plan_json.get("aggregation") or {}).get("group_by") or []):
            row = column_lookup.get(str(key or "").strip().lower())
            col = _to_sql_column_key(row)
            if col is None:
                continue
            edits.append(AddGroupByEdit(op="addGroupBy", col=col))

        for item in list((plan_json.get("aggregation") or {}).get("metrics") or []):
            ref_kind, ref_value = _split_metric_ref(item.get("metric_ref"), fallback_column_key=item.get("column_key"))
            if ref_kind == "column":
                agg = str(item.get("agg") or "").strip().lower()
                if agg not in {"count", "count_distinct", "sum", "avg"}:
                    continue
                row = column_lookup.get(ref_value)
                col = _to_sql_column_key(row) if row is not None else None
                edits.append(
                    AddAggregateEdit(
                        op="addAggregate",
                        func=agg,
                        col=col,
                        alias=str(item.get("label") or f"{agg}_metric"),
                    )
                )
                continue

            if ref_kind == "derived":
                derived = derived_lookup.get(ref_value)
                if not isinstance(derived, dict):
                    continue
                expr_payload = _compile_derived_ratio_expr_payload(
                    derived=derived,
                    column_lookup=column_lookup,
                )
                if expr_payload is None:
                    continue
                derived_agg_metrics.append(
                    {
                        "id": f"derived_{ref_value}",
                        "fn": "expr",
                        "field": None,
                        "label": str(item.get("label") or derived.get("name") or ref_value),
                        "expr": expr_payload,
                    }
                )

        sql_json = apply_edits(None, edits, prompt=prompt)
        if derived_agg_metrics:
            aggs = sql_json.get("aggs")
            if not isinstance(aggs, dict):
                aggs = {"enabled": True, "groupBy": [], "metrics": []}
                sql_json["aggs"] = aggs
            aggs["enabled"] = True
            if not isinstance(aggs.get("metrics"), list):
                aggs["metrics"] = []
            aggs["metrics"].extend(derived_agg_metrics)
        meta = sql_json.get("meta")
        if isinstance(meta, dict):
            meta["tool"] = "planner_llm_v2"
            meta["plan_json"] = plan_json
        return sql_json


def normalize_prompt_for_planner(prompt: str) -> str:
    text = str(prompt or "")
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", " ", text)
    text = re.sub(r"[;`\"\\]", " ", text)
    text = re.sub(r"\s+", " ", text).strip().lower()
    return text


def _looks_like_plan_json(payload: Dict[str, Any]) -> bool:
    required = ("intent", "grain", "selects", "filters", "domains", "aggregation", "derived_metrics")
    return all(key in payload for key in required)


def _split_metric_ref(metric_ref: Any, *, fallback_column_key: Any = None) -> Tuple[str, str]:
    ref = str(metric_ref or "").strip().lower()
    if ref == "":
        fallback = str(fallback_column_key or "").strip().lower()
        return ("column", fallback) if fallback else ("", "")
    if ref.startswith("column:"):
        return "column", ref.split(":", 1)[1].strip()
    if ref.startswith("derived:"):
        return "derived", ref.split(":", 1)[1].strip()
    return "column", ref


def _compile_derived_ratio_expr_payload(
    *,
    derived: Dict[str, Any],
    column_lookup: Mapping[str, Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    kind = str(derived.get("kind") or "").strip().lower()
    if kind != "ratio":
        return None
    numerator = derived.get("numerator") if isinstance(derived.get("numerator"), dict) else {}
    denominator = derived.get("denominator") if isinstance(derived.get("denominator"), dict) else {}
    num_key = str(numerator.get("column_key") or "").strip().lower()
    den_key = str(denominator.get("column_key") or "").strip().lower()
    num_row = column_lookup.get(num_key)
    den_row = column_lookup.get(den_key)
    if not isinstance(num_row, dict) or not isinstance(den_row, dict):
        return None
    num_col = _to_sql_column_key(num_row)
    den_col = _to_sql_column_key(den_row)
    if num_col is None or den_col is None:
        return None
    num_agg = _normalize_expr_agg(numerator.get("agg"))
    den_agg = _normalize_expr_agg(denominator.get("agg"))
    if num_agg is None or den_agg is None:
        return None
    return {
        "kind": "ratio",
        "numerator": {"fn": num_agg, "field": num_col.model_dump(mode="json", exclude_none=False)},
        "denominator": {"fn": den_agg, "field": den_col.model_dump(mode="json", exclude_none=False)},
        "safe_divide": bool(derived.get("safe_divide", True)),
    }


def _normalize_expr_agg(value: Any) -> Optional[str]:
    token = str(value or "").strip().lower()
    if token in {"count", "count_distinct", "sum", "avg", "min", "max"}:
        return token
    return None


def _norm_vertical(vertical: str) -> str:
    value = str(vertical or "generic").strip().lower()
    if value in {"education", "healthcare", "generic"}:
        return value
    return "generic"


def _column_key(workspace_table_id: int, column_name: str) -> str:
    return f"wt{int(workspace_table_id)}.{str(column_name).strip().lower()}"


def _is_pii_column(*, column_name: str, semantic_type: str) -> bool:
    name = str(column_name or "").strip().lower()
    semantic = str(semantic_type or "").strip().lower()
    if semantic in {"pii", "sensitive"}:
        return True
    pii_tokens = ("name", "email", "phone", "ssn", "address", "dob", "birth")
    return any(token in name for token in pii_tokens)


def _parse_json_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return list(value)
    text = str(value or "").strip()
    if text == "":
        return []
    try:
        parsed = json.loads(text)
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    return parsed if isinstance(parsed, list) else []


def _to_int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _to_sql_column_key(row: Optional[Dict[str, Any]]) -> Optional[SqlColumnKey]:
    if not isinstance(row, dict):
        return None
    column_name = str(row.get("column_name") or "").strip()
    if column_name == "":
        return None
    return SqlColumnKey(
        modelColumnId=_to_int(row.get("model_column_id")),
        columnName=column_name,
        workspaceTableId=_to_int(row.get("workspace_table_id")),
        exprId=None,
        alias=None,
    )


def _to_filter_operator(value: Any) -> Optional[str]:
    token = str(value or "").strip().lower()
    mapping = {
        "equals": "equals",
        "=": "equals",
        "==": "equals",
        "eq": "equals",
        "not_equals": "not_equals",
        "not_equal": "not_equals",
        "ne": "not_equals",
        "!=": "not_equals",
        "<>": "not_equals",
        "contains": "contains",
        "like": "contains",
        "starts_with": "starts_with",
        "startswith": "starts_with",
        "prefix": "starts_with",
        "in": "in",
        "not_in": "not_in",
        "not in": "not_in",
        "gt": "gt",
        ">": "gt",
        "gte": "gte",
        ">=": "gte",
        "lt": "lt",
        "<": "lt",
        "lte": "lte",
        "<=": "lte",
        "between": "between",
        "exists": "is_not_null",
        "is_not_null": "is_not_null",
        "is not null": "is_not_null",
        "not_exists": "is_null",
        "is_null": "is_null",
        "is null": "is_null",
    }
    return mapping.get(token)


def _filter_value_for_operator(*, item: Dict[str, Any], operator: str) -> Any:
    if operator in {"is_null", "is_not_null"}:
        return None
    if operator in {"in", "not_in", "between"} and isinstance(item.get("values"), list):
        return list(item.get("values") or [])
    return item.get("value")


def _in_clause(prefix: str, values: Sequence[int]) -> Tuple[str, Dict[str, Any]]:
    names: List[str] = []
    params: Dict[str, Any] = {}
    for idx, value in enumerate(values):
        key = f"{prefix}{idx}"
        names.append(f":{key}")
        params[key] = int(value)
    return ", ".join(names), params


def _elapsed_ms(start: float) -> int:
    return int((perf_counter() - start) * 1000)


__all__ = ["PlannerLLMService", "PlannerLLMCandidateRetriever", "PlannerLLMRequest", "normalize_prompt_for_planner"]
