from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.adapters.mysql_sql_executor import MySQLSQLExecutor
from app.config import SEMANTIC_PLAN_LLM_MODEL, SEMANTIC_PLAN_LLM_TIMEOUT_SECONDS, VLLM_BASE_URL
from app.exceptions.service_error import ServiceError
from app.ports.sql_executor import SQLExecutor
from app.services.llm.llm_client import LLMClient
from app.services.semantic.concept_retrieval_service import ConceptRetrievalService
from app.services.semantic.concept_to_column_service import ConceptToColumnService
from app.services.semantic.constrained_column_vector_service import ConstrainedColumnVectorService
from app.services.semantic.deterministic_matcher import DeterministicMatcher


class PlanningRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    workspace_id: str
    vertical_norm: str = "generic"
    prompt: str
    domain_id: Optional[int] = None
    max_concepts: int = 12
    max_columns: int = 60
    debug: bool = False


class LLMSelectedColumn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    concept_key: str
    model_column_id: int


class LLMFilter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    concept_key: str
    op: str
    value: Any


class LLMPlanPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sql_json: Dict[str, Any]
    selected_columns: List[LLMSelectedColumn] = Field(default_factory=list)
    filters: List[LLMFilter] = Field(default_factory=list)
    join_plan: Dict[str, Any] = Field(default_factory=dict)
    confidence: float = Field(ge=0.0, le=1.0)
    notes: List[str] = Field(default_factory=list)


class PlanService:
    def __init__(
        self,
        *,
        sql: Optional[SQLExecutor] = None,
        deterministic: Optional[DeterministicMatcher] = None,
        concept_retrieval: Optional[ConceptRetrievalService] = None,
        concept_to_column: Optional[ConceptToColumnService] = None,
        column_vector: Optional[ConstrainedColumnVectorService] = None,
        llm_client: Optional[LLMClient] = None,
    ) -> None:
        self._sql = sql or MySQLSQLExecutor()
        self._deterministic = deterministic or DeterministicMatcher()
        self._concept_retrieval = concept_retrieval or ConceptRetrievalService()
        self._concept_to_column = concept_to_column or ConceptToColumnService(sql=self._sql)
        self._column_vector = column_vector or ConstrainedColumnVectorService()
        self._llm = llm_client or LLMClient(
            endpoint=VLLM_BASE_URL,
            model=SEMANTIC_PLAN_LLM_MODEL,
            timeout_seconds=SEMANTIC_PLAN_LLM_TIMEOUT_SECONDS,
        )

    def plan(self, payload: Dict[str, Any], *, include_llm: bool = True) -> Dict[str, Any]:
        try:
            req = PlanningRequest.model_validate(payload or {})
        except ValidationError as exc:
            raise ServiceError("Invalid planning request", status_code=400, details={"errors": exc.errors()}) from exc

        workspace_id = str(req.workspace_id or "").strip()
        vertical_norm = str(req.vertical_norm or "generic").strip().lower() or "generic"
        prompt = str(req.prompt or "").strip()
        if workspace_id == "" or prompt == "":
            raise ServiceError("workspace_id and prompt are required", status_code=400)

        max_concepts = max(1, min(24, int(req.max_concepts)))
        max_columns = max(1, min(120, int(req.max_columns)))

        timings_ms: Dict[str, int] = {}
        warnings: List[str] = []

        t0 = time.perf_counter()
        deterministic = self._deterministic.match(prompt)
        timings_ms["deterministic"] = _elapsed_ms(t0)

        t1 = time.perf_counter()
        concept_vector = self._concept_retrieval.search(
            prompt=prompt,
            vertical_norm=vertical_norm,
            max_concepts=max_concepts,
            deterministic_matches=deterministic.get("matched") if isinstance(deterministic, dict) else None,
        )
        concept_vector["hits"] = concept_vector.get("hits", [])[:max_concepts]
        concept_keys = [str(hit.get("concept_key") or "").upper() for hit in concept_vector.get("hits", [])]
        concept_info = self._load_concept_details(vertical_norm=vertical_norm, concept_keys=concept_keys)
        timings_ms["concept_vector"] = _elapsed_ms(t1)

        t2 = time.perf_counter()
        concept_mapping = self._concept_to_column.map_concepts_to_columns(
            workspace_id=workspace_id,
            vertical_norm=vertical_norm,
            concept_hits=concept_vector.get("hits", []),
            max_columns=max_columns,
            domain_id=req.domain_id,
        )
        concept_mapping["mapped_columns"] = concept_mapping.get("mapped_columns", [])[:max_columns]
        timings_ms["concept_mapping"] = _elapsed_ms(t2)

        t3 = time.perf_counter()
        column_vector = self._column_vector.search(
            prompt=prompt,
            workspace_id=workspace_id,
            candidate_columns=concept_mapping.get("mapped_columns", []),
            concept_hits=concept_vector.get("hits", []),
            max_columns=max_columns,
        )
        column_vector["hits"] = column_vector.get("hits", [])[:max_columns]
        timings_ms["column_vector"] = _elapsed_ms(t3)

        response: Dict[str, Any] = {
            "prompt": prompt,
            "deterministic": deterministic,
            "concept_vector": concept_vector,
            "concept_mapping": {
                "concepts": concept_mapping.get("concepts", []),
                "mapped_columns": concept_mapping.get("mapped_columns", []),
            },
            "column_vector": column_vector,
        }

        if include_llm:
            t4 = time.perf_counter()
            llm_plan = self._plan_with_llm(
                prompt=prompt,
                concept_hits=concept_vector.get("hits", []),
                concept_info=concept_info,
                mapped_columns=concept_mapping.get("mapped_columns", []),
                column_hits=column_vector.get("hits", []),
                max_concepts=max_concepts,
                max_columns=max_columns,
            )
            timings_ms["llm"] = _elapsed_ms(t4)
            response["llm_plan"] = {
                "model": SEMANTIC_PLAN_LLM_MODEL,
                **llm_plan,
            }
        else:
            timings_ms["llm"] = 0

        response["debug"] = {
            "timings_ms": timings_ms,
            "warnings": warnings,
        }
        return response

    def _plan_with_llm(
        self,
        *,
        prompt: str,
        concept_hits: Sequence[Dict[str, Any]],
        concept_info: Dict[str, Dict[str, Any]],
        mapped_columns: Sequence[Dict[str, Any]],
        column_hits: Sequence[Dict[str, Any]],
        max_concepts: int,
        max_columns: int,
    ) -> Dict[str, Any]:
        concepts_for_llm: List[Dict[str, Any]] = []
        for hit in concept_hits[:max_concepts]:
            key = str(hit.get("concept_key") or "").upper()
            info = concept_info.get(key, {})
            concepts_for_llm.append(
                {
                    "concept_key": key,
                    "semantic_type": info.get("semantic_type"),
                    "sub_type": info.get("sub_type"),
                    "entity": info.get("entity"),
                    "description": _trim(str(info.get("description") or ""), 180),
                    "score": hit.get("score"),
                    "source": hit.get("source"),
                }
            )

        by_mid: Dict[int, Dict[str, Any]] = {}
        for row in list(column_hits) + list(mapped_columns):
            try:
                mid = int(row.get("model_column_id"))
            except Exception:
                continue
            existing = by_mid.get(mid)
            if existing is None:
                by_mid[mid] = {
                    "model_column_id": mid,
                    "table_name": row.get("table_name"),
                    "column_name": row.get("column_name"),
                    "concept_key": row.get("concept_key"),
                    "weight": row.get("weight"),
                    "score": row.get("score"),
                }
            else:
                if existing.get("score") is None and row.get("score") is not None:
                    existing["score"] = row.get("score")
                if not existing.get("concept_key") and row.get("concept_key"):
                    existing["concept_key"] = row.get("concept_key")

        columns_for_llm = list(by_mid.values())[:max_columns]

        system_prompt = (
            "You are a query planner. Return JSON only with keys: sql_json, selected_columns, filters, join_plan, confidence, notes. "
            "Do not include markdown or extra keys. "
            "selected_columns must be an array of objects: {concept_key, model_column_id}. "
            "filters must be an array of objects: {concept_key, op, value}. "
            "join_plan must be an object. notes must be an array of strings."
        )
        user_prompt = (
            "Build a query plan from this input.\n"
            f"User prompt: {prompt}\n"
            f"Concepts: {json.dumps(concepts_for_llm, ensure_ascii=True)}\n"
            f"Candidate columns: {json.dumps(columns_for_llm, ensure_ascii=True)}\n"
            "Return strict JSON only."
        )

        payload = self._llm.chat_json(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_format=True,
            retry_invalid_schema=True,
            validator=lambda body: (
                isinstance(body.get("sql_json"), dict)
                and isinstance(body.get("selected_columns"), list)
                and isinstance(body.get("filters"), list)
            ),
        )
        payload = self._normalize_llm_payload(payload, candidate_columns=columns_for_llm)

        try:
            parsed = LLMPlanPayload.model_validate(payload)
        except ValidationError as exc:
            raise ServiceError(
                "Invalid LLM planning response",
                status_code=502,
                details={"errors": exc.errors(), "payload": payload},
            ) from exc

        grounded = self._ground_plan(parsed, columns_for_llm, concepts_for_llm)
        return grounded

    @staticmethod
    def _normalize_llm_payload(
        payload: Dict[str, Any],
        *,
        candidate_columns: Sequence[Dict[str, Any]],
    ) -> Dict[str, Any]:
        if not isinstance(payload, dict):
            return {}

        normalized: Dict[str, Any] = dict(payload)
        normalized.setdefault("sql_json", {})

        concept_by_model_column_id: Dict[int, str] = {}
        concept_by_table_column: Dict[Tuple[str, str], str] = {}
        concept_by_column_name: Dict[str, Optional[str]] = {}
        for row in candidate_columns:
            mid = _to_int(row.get("model_column_id"))
            concept_key = str(row.get("concept_key") or "").strip().upper()
            table_name = str(row.get("table_name") or "").strip().lower()
            column_name = str(row.get("column_name") or "").strip().lower()
            if mid is not None and concept_key:
                concept_by_model_column_id[mid] = concept_key
            if table_name and column_name and concept_key:
                concept_by_table_column[(table_name, column_name)] = concept_key
            if column_name and concept_key:
                if column_name in concept_by_column_name and concept_by_column_name[column_name] != concept_key:
                    concept_by_column_name[column_name] = None
                elif column_name not in concept_by_column_name:
                    concept_by_column_name[column_name] = concept_key

        selected_columns: List[Dict[str, Any]] = []
        raw_selected = normalized.get("selected_columns")
        if isinstance(raw_selected, list):
            for item in raw_selected:
                if isinstance(item, (int, float, str)):
                    mid = _to_int(item)
                    if mid is None:
                        continue
                    concept_key = concept_by_model_column_id.get(mid)
                    if not concept_key:
                        continue
                    selected_columns.append({"concept_key": concept_key, "model_column_id": mid})
                    continue
                if isinstance(item, dict):
                    mid = _to_int(item.get("model_column_id"))
                    if mid is None:
                        mid = _to_int(item.get("modelColumnId"))
                    if mid is None:
                        continue
                    concept_key = str(item.get("concept_key") or item.get("conceptKey") or "").strip().upper()
                    if concept_key == "":
                        concept_key = concept_by_model_column_id.get(mid, "")
                    if concept_key == "":
                        continue
                    selected_columns.append({"concept_key": concept_key, "model_column_id": mid})
        normalized["selected_columns"] = selected_columns

        filters: List[Dict[str, Any]] = []
        raw_filters = normalized.get("filters")
        if isinstance(raw_filters, list):
            for item in raw_filters:
                if not isinstance(item, dict):
                    continue
                mid = _to_int(item.get("model_column_id"))
                if mid is None:
                    mid = _to_int(item.get("modelColumnId"))
                concept_key = str(item.get("concept_key") or item.get("conceptKey") or "").strip().upper()
                if concept_key == "" and mid is not None:
                    concept_key = concept_by_model_column_id.get(mid, "")
                if concept_key == "":
                    column_expr = str(item.get("column") or "").strip().lower()
                    if column_expr:
                        parts = [p for p in column_expr.split(".") if p]
                        if len(parts) >= 2:
                            concept_key = concept_by_table_column.get((parts[-2], parts[-1]), "")
                        if concept_key == "" and parts:
                            concept_key = concept_by_column_name.get(parts[-1]) or ""
                op = str(item.get("op") or item.get("operator") or "").strip()
                if concept_key == "" or op == "":
                    continue
                filters.append(
                    {
                        "concept_key": concept_key,
                        "op": op,
                        "value": item.get("value"),
                    }
                )
        normalized["filters"] = filters

        raw_join_plan = normalized.get("join_plan")
        if isinstance(raw_join_plan, list):
            normalized["join_plan"] = {"joins": raw_join_plan}
        elif isinstance(raw_join_plan, dict):
            normalized["join_plan"] = raw_join_plan
        else:
            normalized["join_plan"] = {}

        raw_notes = normalized.get("notes")
        if isinstance(raw_notes, str):
            notes = [raw_notes.strip()] if raw_notes.strip() else []
        elif isinstance(raw_notes, list):
            notes = [str(n).strip() for n in raw_notes if str(n).strip()]
        else:
            notes = []
        normalized["notes"] = notes

        confidence = _to_float(normalized.get("confidence"))
        if confidence is None:
            confidence = 0.5
        normalized["confidence"] = max(0.0, min(1.0, confidence))
        return normalized

    @staticmethod
    def _ground_plan(
        plan: LLMPlanPayload,
        candidate_columns: Sequence[Dict[str, Any]],
        concepts: Sequence[Dict[str, Any]],
    ) -> Dict[str, Any]:
        valid_mids = {int(col.get("model_column_id")) for col in candidate_columns if col.get("model_column_id") is not None}
        valid_concepts = {str(item.get("concept_key") or "").upper() for item in concepts if item.get("concept_key")}

        selected_columns = [
            item.model_dump(mode="json")
            for item in plan.selected_columns
            if int(item.model_column_id) in valid_mids
        ]
        filters = [
            item.model_dump(mode="json")
            for item in plan.filters
            if str(item.concept_key or "").upper() in valid_concepts
        ]

        removed = (len(plan.selected_columns) - len(selected_columns)) + (len(plan.filters) - len(filters))
        confidence = float(plan.confidence)
        notes = list(plan.notes)
        if removed > 0:
            confidence = max(0.0, confidence - min(0.2, removed * 0.03))
            notes.append(f"grounding_removed={removed}")

        return {
            "sql_json": plan.sql_json,
            "selected_columns": selected_columns,
            "filters": filters,
            "join_plan": plan.join_plan,
            "confidence": round(confidence, 4),
            "notes": notes,
        }

    def _load_concept_details(self, *, vertical_norm: str, concept_keys: Sequence[str]) -> Dict[str, Dict[str, Any]]:
        keys = [str(k or "").strip().upper() for k in concept_keys if str(k or "").strip()]
        if not keys:
            return {}
        in_sql, in_params = _in_clause("ck", keys)
        rows = self._sql.execute_query_mappings(
            f"""
            SELECT
              concept_key,
              semantic_type,
              sub_type,
              entity,
              description
            FROM semantic_concept
            WHERE concept_key IN ({in_sql})
              AND vertical_norm IN (:vertical_norm, 'generic')
              AND `status` = 'active'
            ORDER BY CASE WHEN vertical_norm = :vertical_norm THEN 0 ELSE 1 END
            """,
            {
                **in_params,
                "vertical_norm": str(vertical_norm or "generic").strip().lower() or "generic",
            },
        )
        out: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            key = str(row.get("concept_key") or "").upper()
            if key and key not in out:
                out[key] = dict(row)
        return out


def _elapsed_ms(start: float) -> int:
    return int((time.perf_counter() - start) * 1000)


def _trim(value: str, size: int) -> str:
    text = str(value or "").strip()
    if len(text) <= size:
        return text
    return text[:size].rstrip()


def _to_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except Exception:
        return None


def _to_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except Exception:
        return None


def _in_clause(prefix: str, values: Sequence[str]) -> Tuple[str, Dict[str, Any]]:
    params: Dict[str, Any] = {}
    names: List[str] = []
    for idx, val in enumerate(values):
        key = f"{prefix}{idx}"
        names.append(f":{key}")
        params[key] = str(val)
    return ", ".join(names), params


__all__ = ["PlanService"]
