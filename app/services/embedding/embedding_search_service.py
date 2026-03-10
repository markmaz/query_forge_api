from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Sequence

from qdrant_client.http import models as qdrant_models

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.config import (
    QDRANT_COLUMN_COLLECTION,
    QDRANT_COLUMN_COLLECTION_V2,
    QDRANT_DOMAIN_COLLECTION,
    QDRANT_TABLE_COLLECTION,
)
from app.exceptions.forge_error import ForgeError
from app.infra.embedding_model import EmbeddingModel
from app.infra.qdrant_client import QdrantClientWrapper, build_payload_filter
from app.ports.sql_executor import ForgeQueryPort
from app.services.embedding.domain_embedding_service import build_domain_point_id

logger = logging.getLogger(__name__)

TABLE_COLLECTION_NAME = QDRANT_TABLE_COLLECTION or "table_catalog"
COLUMN_COLLECTION_NAME = QDRANT_COLUMN_COLLECTION_V2 or QDRANT_COLUMN_COLLECTION or "column_catalog_v2"
DOMAIN_COLLECTION_NAME = QDRANT_DOMAIN_COLLECTION or "domain_catalog"
DEFAULT_LIMIT = 10
MAX_LIMIT = 50
ALLOWED_KINDS = {"table", "column", "domain"}
STOPWORDS = {
    "the",
    "a",
    "an",
    "of",
    "to",
    "and",
    "or",
    "in",
    "on",
    "for",
    "by",
    "with",
    "this",
    "that",
    "how",
    "many",
    "show",
    "what",
    "which",
    "are",
    "is",
    "were",
    "was",
}


def detect_semantic_intent(prompt: str) -> Dict[str, Any]:
    text = (prompt or "").strip().lower()

    geography_level = None
    if "city" in text:
        geography_level = "city"
    elif "county" in text:
        geography_level = "county"
    elif "state" in text:
        geography_level = "state"
    elif "zip" in text or "postal" in text:
        geography_level = "zip"

    wants_aggregation = any(
        token in text
        for token in ("how many", "count", "total", "sum", "average", "avg", "number of")
    )
    wants_listing = any(token in text for token in ("show", "list", "display", "give me", "all"))
    wants_grade_level = any(token in text for token in ("grade level", "grade", "3rd", "4th", "5th"))

    entity_type = None
    if "student" in text:
        entity_type = "student"
    elif "school" in text:
        entity_type = "school"
    elif "course" in text:
        entity_type = "course"
    elif "district" in text:
        entity_type = "district"

    time_reference = None
    if "school year" in text:
        time_reference = "school_year"
    elif "calendar year" in text:
        time_reference = "calendar_year"
    else:
        year_match = re.search(r"\b(19|20)\d{2}\b", text)
        if year_match:
            time_reference = year_match.group(0)
        elif "today" in text:
            time_reference = "today"
        elif "yesterday" in text:
            time_reference = "yesterday"

    return {
        "geography_level": geography_level,
        "wants_aggregation": wants_aggregation,
        "wants_listing": wants_listing,
        "wants_grade_level": wants_grade_level,
        "entity_type": entity_type,
        "time_reference": time_reference,
    }


class EmbeddingSearchService:
    def __init__(
        self,
        *,
        table_qdrant: Optional[QdrantClientWrapper] = None,
        column_qdrant: Optional[QdrantClientWrapper] = None,
        domain_qdrant: Optional[QdrantClientWrapper] = None,
        sql: Optional[ForgeQueryPort] = None,
        model: Optional[EmbeddingModel] = None,
    ) -> None:
        self._table_qdrant = table_qdrant or QdrantClientWrapper(collection_name=TABLE_COLLECTION_NAME)
        self._column_qdrant = column_qdrant or QdrantClientWrapper(collection_name=COLUMN_COLLECTION_NAME)
        self._domain_qdrant = domain_qdrant or QdrantClientWrapper(collection_name=DOMAIN_COLLECTION_NAME)
        self._sql = sql or ForgeMetaSQL()
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
            raise ForgeError("query is required", status_code=400)

        limit_val = _clamp_limit(limit)
        kinds_list = _normalize_kinds(kinds)
        include_domain = "domain" in kinds_list
        include_table = "table" in kinds_list
        include_column = "column" in kinds_list

        origin_val = (origin or "").strip() or None
        source_table_val = (source_table_name or "").strip() or None
        semantic_intent = detect_semantic_intent(query_text)
        logger.info("Embedding search semantic_intent=%s", semantic_intent)

        query_vector = self._model.encode([query_text], normalize=True)[0]

        workspace_table_ids: Optional[List[int]] = None
        if domain_id is not None:
            if not workspace_id:
                raise ForgeError("workspace_id is required when domain_id is provided", status_code=400)
            workspace_table_ids = self._resolve_domain_workspace_table_ids(workspace_id, int(domain_id))

        table_hits: List[Dict[str, Any]] = []
        column_hits: List[Dict[str, Any]] = []
        domain_hits: List[Dict[str, Any]] = []

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
                score = float(hit.score or 0.0)
                table_hits.append(
                    {
                        "kind": "table",
                        "rawScore": score,
                        "modelTableId": payload.get("model_table_id"),
                        "tableName": payload.get("source_table_name"),
                        "origin": payload.get("origin"),
                        "externalId": payload.get("external_id"),
                        "semanticType": payload.get("semantic_type"),
                        "_payload": payload,
                    }
                )

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
                    column_hits.append(
                        {
                            "kind": "column",
                            "rawScore": score,
                            "workspaceId": payload.get("workspace_id"),
                            "workspaceTableId": payload.get("workspace_table_id"),
                            "workspaceColumnId": payload.get("workspace_column_id"),
                            "modelTableId": payload.get("model_table_id"),
                            "modelColumnId": payload.get("model_column_id"),
                            "tableName": payload.get("table_name"),
                            "columnName": payload.get("column_name"),
                            "dataType": payload.get("data_type"),
                            "description": payload.get("description"),
                            "semanticType": payload.get("semantic_type"),
                            "_payload": payload,
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
                domain_hits.append(
                    {
                        "kind": "domain",
                        "rawScore": score,
                        "domainId": payload.get("domain_id"),
                        "domainName": payload.get("domain_name"),
                            "domainKind": payload.get("domain_kind"),
                            "workspaceId": payload.get("workspace_id"),
                            "semanticType": payload.get("semantic_type"),
                            "_payload": payload,
                        }
                    )

        table_hits = _apply_hybrid_scoring(
            table_hits,
            query_text=query_text,
            workspace_id=workspace_id,
            domain_id=domain_id,
            workspace_table_ids=workspace_table_ids,
            origin=origin_val,
            model_table_id=model_table_id,
            source_table_name=source_table_val,
            semantic_intent=semantic_intent,
        )
        column_hits = _apply_hybrid_scoring(
            column_hits,
            query_text=query_text,
            workspace_id=workspace_id,
            domain_id=domain_id,
            workspace_table_ids=workspace_table_ids,
            origin=origin_val,
            model_table_id=model_table_id,
            source_table_name=source_table_val,
            semantic_intent=semantic_intent,
        )
        domain_hits = _apply_hybrid_scoring(
            domain_hits,
            query_text=query_text,
            workspace_id=workspace_id,
            domain_id=domain_id,
            workspace_table_ids=workspace_table_ids,
            origin=origin_val,
            model_table_id=model_table_id,
            source_table_name=source_table_val,
            semantic_intent=semantic_intent,
        )

        if min_score is not None:
            min_val = float(min_score)
            table_hits = [r for r in table_hits if float(r.get("score", 0.0)) >= min_val]
            column_hits = [r for r in column_hits if float(r.get("score", 0.0)) >= min_val]
            domain_hits = [r for r in domain_hits if float(r.get("score", 0.0)) >= min_val]

        grouped = _group_results(
            tables=table_hits,
            columns=column_hits,
            domains=domain_hits,
            limit=limit_val,
        )

        logger.info(
            "Embedding search: query=%s limit=%s kinds=%s results=%s",
            query_text,
            limit_val,
            kinds_list,
            len(grouped.get("combined", [])),
        )

        return {
            "query": query_text,
            "limit": limit_val,
            "kinds": kinds_list,
            "results": {
                "tables": grouped["tables"],
                "columns": grouped["columns"],
                "domains": grouped["domains"],
            },
            "combined": grouped["combined"],
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
        raise ForgeError("kinds must be an array", status_code=400)

    normalized = []
    for kind in kinds:
        if not isinstance(kind, str):
            raise ForgeError("kinds must be an array of strings", status_code=400)
        value = kind.strip().lower()
        if value:
            normalized.append(value)

    if not normalized:
        raise ForgeError("kinds cannot be empty", status_code=400)

    invalid = [k for k in normalized if k not in ALLOWED_KINDS]
    if invalid:
        raise ForgeError(f"invalid kinds: {', '.join(invalid)}", status_code=400)

    return list(dict.fromkeys(normalized))


def _tokenize_query(query_text: str) -> List[str]:
    tokens = re.split(r"[^a-z0-9]+", (query_text or "").lower())
    return [t for t in tokens if t and t not in STOPWORDS]


def _compute_lexical_boost_and_reasons(
    query_text: str,
    *,
    name_fields: Sequence[Optional[str]],
    description: Optional[str] = None,
) -> tuple[float, List[str], List[str]]:
    tokens = _tokenize_query(query_text)
    if not tokens:
        return 0.0, [], []

    boost = 0.0
    reasons: List[str] = []
    matched_tokens: List[str] = []
    reason_set = set()
    matched_set = set()

    description_val = (description or "").lower()

    for token in tokens:
        token_matched = False
        for field in name_fields:
            if not field:
                continue
            field_val = str(field).lower()
            if token == field_val:
                boost += 0.18
                reason_set.add("match.name_exact")
                token_matched = True
            elif field_val.startswith(token):
                boost += 0.12
                reason_set.add("match.name_prefix")
                token_matched = True
            elif token in field_val:
                boost += 0.08
                reason_set.add("match.name_contains")
                token_matched = True

        if description_val and token in description_val:
            boost += 0.04
            reason_set.add("match.name_contains")
            token_matched = True

        if token_matched:
            matched_set.add(token)

    boost = min(boost, 0.25)
    if reason_set:
        reasons = sorted(reason_set)
    if matched_set:
        matched_tokens = sorted(matched_set)

    return boost, reasons, matched_tokens


def _compute_scope_boost_and_reasons(
    *,
    result: Dict[str, Any],
    workspace_id: Optional[str],
    domain_id: Optional[int],
    workspace_table_ids: Optional[Sequence[int]],
) -> tuple[float, List[str]]:
    boost = 0.0
    reasons: List[str] = []

    if domain_id is not None:
        in_domain = False
        if result.get("kind") == "domain":
            try:
                in_domain = int(result.get("domainId") or 0) == int(domain_id)
            except Exception:
                in_domain = False
        elif result.get("kind") == "column" and workspace_table_ids:
            try:
                in_domain = int(result.get("workspaceTableId") or 0) in set(workspace_table_ids)
            except Exception:
                in_domain = False
        if in_domain:
            boost += 0.05
            reasons.append("scoped_to_domain")

    if workspace_id:
        res_ws = result.get("workspaceId") or result.get("workspace_id")
        if res_ws is not None and str(res_ws) == str(workspace_id):
            boost += 0.03
            reasons.append("scoped_to_workspace")

    if boost > 0.08:
        boost = 0.08

    return boost, reasons


def _compute_semantic_boost_and_reasons(
    *,
    semantic_type: Optional[str],
    semantic_intent: Dict[str, Any],
) -> tuple[float, List[str]]:
    sem_type = str(semantic_type or "").strip().lower()
    if not sem_type:
        return 0.0, []

    boost = 0.0
    reasons: List[str] = []
    geography_level = semantic_intent.get("geography_level")
    wants_aggregation = bool(semantic_intent.get("wants_aggregation"))
    wants_listing = bool(semantic_intent.get("wants_listing"))

    if geography_level == "city":
        if sem_type == "geography.city":
            boost += 0.08
            reasons.append("semantic.geography.city")
        elif sem_type == "geography.county":
            boost -= 0.05
            reasons.append("semantic.penalty.geography.county")

    if wants_aggregation and sem_type.startswith("metric."):
        boost += 0.05
        reasons.append("semantic.metric_for_aggregation")

    if wants_listing and sem_type.startswith("identifier."):
        boost += 0.03
        reasons.append("semantic.identifier_for_listing")

    if boost > 0.1:
        boost = 0.1
    if boost < -0.1:
        boost = -0.1
    return boost, reasons


def _is_integer_data_type(data_type: Optional[str]) -> bool:
    text = str(data_type or "").strip().lower()
    if not text:
        return False
    integer_tokens = ("int", "integer", "bigint", "smallint", "tinyint")
    return any(token in text for token in integer_tokens)


def _compute_grade_level_boost_and_reasons(
    *,
    item: Dict[str, Any],
    semantic_intent: Dict[str, Any],
) -> tuple[float, List[str]]:
    if not bool(semantic_intent.get("wants_grade_level")):
        return 0.0, []
    if item.get("kind") != "column":
        return 0.0, []

    col_name = str(item.get("columnName") or "").strip().lower()
    if "grade" not in col_name:
        return 0.0, []

    boost = 0.0
    reasons: List[str] = []
    if col_name in {"grade_level", "gradelevel", "current_grade_level"}:
        boost += 0.05
        reasons.append("semantic.grade_level_column")
    else:
        boost += 0.02
        reasons.append("semantic.grade_related_column")

    if _is_integer_data_type(item.get("dataType")):
        boost += 0.06
        reasons.append("semantic.grade_integer_type")

    if boost > 0.1:
        boost = 0.1
    return boost, reasons


def _apply_hybrid_scoring(
    items: List[Dict[str, Any]],
    *,
    query_text: str,
    workspace_id: Optional[str],
    domain_id: Optional[int],
    workspace_table_ids: Optional[Sequence[int]],
    origin: Optional[str],
    model_table_id: Optional[int],
    source_table_name: Optional[str],
    semantic_intent: Dict[str, Any],
) -> List[Dict[str, Any]]:
    for item in items:
        raw_score = float(item.get("rawScore", 0.0))
        reasons: List[str] = ["vector_similarity"]

        if item.get("kind") == "table":
            lex_boost, lex_reasons, matched_tokens = _compute_lexical_boost_and_reasons(
                query_text,
                name_fields=[item.get("tableName")],
            )
        elif item.get("kind") == "column":
            lex_boost, lex_reasons, matched_tokens = _compute_lexical_boost_and_reasons(
                query_text,
                name_fields=[item.get("columnName"), item.get("tableName")],
                description=item.get("description"),
            )
        else:
            lex_boost, lex_reasons, matched_tokens = _compute_lexical_boost_and_reasons(
                query_text,
                name_fields=[item.get("domainName")],
            )

        reasons.extend(lex_reasons)

        scope_boost, scope_reasons = _compute_scope_boost_and_reasons(
            result=item,
            workspace_id=workspace_id,
            domain_id=domain_id,
            workspace_table_ids=workspace_table_ids,
        )
        reasons.extend(scope_reasons)

        semantic_type = item.get("semanticType")
        if semantic_type is None and isinstance(item.get("_payload"), dict):
            semantic_type = item.get("_payload", {}).get("semantic_type")
        semantic_boost, semantic_reasons = _compute_semantic_boost_and_reasons(
            semantic_type=semantic_type,
            semantic_intent=semantic_intent,
        )
        reasons.extend(semantic_reasons)
        grade_boost, grade_reasons = _compute_grade_level_boost_and_reasons(
            item=item,
            semantic_intent=semantic_intent,
        )
        reasons.extend(grade_reasons)

        if origin and item.get("kind") in ("table", "column"):
            reasons.append("filtered_by_origin")
        if item.get("kind") == "table" and (model_table_id is not None or source_table_name):
            reasons.append("filtered_by_table")

        final_score = raw_score + lex_boost + scope_boost + semantic_boost + grade_boost

        item["rawScore"] = raw_score
        item["semanticType"] = semantic_type
        item["semanticBoost"] = semantic_boost
        item["gradeBoost"] = grade_boost
        item["score"] = final_score
        item["reasons"] = list(dict.fromkeys(reasons))

        highlights: Dict[str, Any] = {"matchedTokens": matched_tokens}
        if item.get("kind") == "table":
            if item.get("tableName") is not None:
                highlights["tableName"] = item.get("tableName")
        elif item.get("kind") == "column":
            if item.get("columnName") is not None:
                highlights["columnName"] = item.get("columnName")
            if item.get("tableName") is not None:
                highlights["tableName"] = item.get("tableName")
        elif item.get("kind") == "domain":
            if item.get("domainName") is not None:
                highlights["domainName"] = item.get("domainName")
        item["highlights"] = highlights

        logger.debug(
            "Embedding semantic scoring kind=%s semantic_type=%s semantic_boost=%s grade_boost=%s semantic_intent=%s",
            item.get("kind"),
            semantic_type,
            semantic_boost,
            grade_boost,
            semantic_intent,
        )

        item.pop("_payload", None)
        description = item.get("description")
        if isinstance(description, str) and len(description) > 240:
            item["description"] = description[:240]

    return items


def _group_results(
    *,
    tables: List[Dict[str, Any]],
    columns: List[Dict[str, Any]],
    domains: List[Dict[str, Any]],
    limit: int,
) -> Dict[str, List[Dict[str, Any]]]:
    tables_sorted = _stable_sort_by_score(tables)[:limit]
    columns_sorted = _stable_sort_by_score(columns)[:limit]
    domains_sorted = _stable_sort_by_score(domains)[:limit]
    combined_sorted = _stable_sort_by_score(tables + columns + domains)[:limit]
    return {
        "tables": tables_sorted,
        "columns": columns_sorted,
        "domains": domains_sorted,
        "combined": combined_sorted,
    }


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


# Example (unit-test-like) for lexical boost:
# query_text = "program"
# boost, reasons, matched = _compute_lexical_boost_and_reasons(
#     query_text,
#     name_fields=["student_program"],
# )
# assert boost > 0.0
# assert "match.name_contains" in reasons
# assert "program" in matched
