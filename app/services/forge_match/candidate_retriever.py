from __future__ import annotations

import logging
import os
import uuid
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.exceptions.forge_error import ForgeError
from app.ports.sql_executor import ForgeQueryPort
from app.services.embedding.embedding_search_service import EmbeddingSearchService
from app.services.forge_match.field_extractor import SourceFieldRecord
from app.services.forge_match.pipeline_definition import build_forge_match_candidate_pipeline_definition
from app.services.forge_match.normalizer import normalize_identifier, normalize_text, split_identifier, token_overlap_score, token_set
from app.services.shared_ai.adapters.candidates import candidate_from_column_row, candidate_to_dict
from app.services.shared_ai.adapters.capabilities import CandidateCapabilityAdapter, HeuristicColumnCapabilityAdapter
from app.services.shared_ai.adapters.policies import CandidatePolicyRerankAdapter, SignalCapabilityRerankAdapter
from app.services.shared_ai.artifacts import CandidateSetArtifact
from app.services.shared_ai.context import PipelineContext
from app.services.shared_ai.executor import PipelineExecutor

logger = logging.getLogger(__name__)
VECTOR_RETRIEVAL_FALLBACK_ERRORS = (ForgeError, OSError, RuntimeError, TypeError, ValueError)


def _is_vector_enabled() -> bool:
    raw = os.getenv("FORGE_MATCH_VECTOR_ENABLED")
    if raw is not None and str(raw).strip() != "":
        return str(raw).strip().lower() in {"1", "true", "yes", "y", "on"}
    return True


@dataclass(frozen=True)
class RetrievedCandidate:
    column_id: int
    workspace_table_id: int
    column_name: str
    display_name: str
    table_name: str
    domain_id: Optional[int]
    domain_name: Optional[str]
    description: Optional[str]
    data_type: Optional[str]
    semantic_type: Optional[str]
    entity: Optional[str]
    preferred_domain_match: bool
    vector_score: float
    lexical_score: float
    combined_retrieval_score: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "column_id": self.column_id,
            "workspace_table_id": self.workspace_table_id,
            "column_name": self.column_name,
            "display_name": self.display_name,
            "table_name": self.table_name,
            "domain_id": self.domain_id,
            "domain_name": self.domain_name,
            "description": self.description,
            "data_type": self.data_type,
            "semantic_type": self.semantic_type,
            "entity": self.entity,
            "preferred_domain_match": self.preferred_domain_match,
            "vector_score": round(float(self.vector_score), 4),
            "lexical_score": round(float(self.lexical_score), 4),
            "combined_retrieval_score": round(float(self.combined_retrieval_score), 4),
        }


class ForgeMatchCandidateRetriever:
    def __init__(
        self,
        *,
        sql: Optional[ForgeQueryPort] = None,
        vector_search: Optional[EmbeddingSearchService] = None,
        pipeline_executor: Optional[PipelineExecutor] = None,
        capability_adapter: Optional[CandidateCapabilityAdapter] = None,
        policy_adapter: Optional[CandidatePolicyRerankAdapter] = None,
    ) -> None:
        self._sql = sql or ForgeMetaSQL()
        vector_enabled = _is_vector_enabled()
        if vector_search is not None:
            self._vector = vector_search
        elif vector_enabled:
            self._vector = EmbeddingSearchService()
        else:
            self._vector = None
            logger.info("ForgeMatch vector retrieval disabled (FORGE_MATCH_VECTOR_ENABLED=false or macOS default)")
        self._pipeline_executor = pipeline_executor or PipelineExecutor()
        self._capability_adapter = capability_adapter or HeuristicColumnCapabilityAdapter()
        self._policy_adapter = policy_adapter or SignalCapabilityRerankAdapter()
        self._last_pipeline_context: Optional[PipelineContext] = None

    def retrieve(
        self,
        *,
        workspace_id: str,
        source_record: SourceFieldRecord,
        top_n: int = 8,
        domain_id: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        ws = str(workspace_id or "").strip()
        if ws == "":
            raise ForgeError("workspace_id is required", status_code=400)

        limit = max(3, min(30, int(top_n or 8)))
        context = PipelineContext(
            pipeline_name="forge_match_candidate_pipeline",
            trace_id=f"forge_match_{uuid.uuid4().hex}",
            workspace_id=ws,
            user_id=None,
            request={
                "prompt": str(source_record.normalized_search_text or source_record.source_field_name or "").strip(),
                "source_record": source_record,
                "top_n": limit,
                "domain_id": int(domain_id) if domain_id is not None else None,
                "preferred_domain_id": int(domain_id) if domain_id is not None else None,
            },
        )
        definition = build_forge_match_candidate_pipeline_definition(
            retrieval_adapter=ForgeMatchColumnRetrievalAdapter(owner=self),
            capability_adapter=self._capability_adapter,
            policy_adapter=self._policy_adapter,
        )
        context = self._pipeline_executor.execute(definition, context)
        self._last_pipeline_context = context

        reranked = context.get_artifact("reranked_candidates", node_name="forge_match_candidate_pipeline")
        candidates = list(getattr(reranked, "candidates", []) or [])
        return [candidate_to_dict(candidate) for candidate in candidates[:limit]]

    @property
    def last_pipeline_context(self) -> Optional[PipelineContext]:
        return self._last_pipeline_context

    def _retrieve_initial_candidates(
        self,
        *,
        workspace_id: str,
        source_record: SourceFieldRecord,
        top_n: int,
        preferred_domain_id: Optional[int],
    ) -> List[Dict[str, Any]]:
        limit = max(3, min(30, int(top_n or 8)))
        lexical_rows = self._load_lexical_candidates(
            workspace_id=workspace_id,
            source_record=source_record,
            domain_id=None,
            max_rows=max(240, limit * 20),
        )

        by_col: dict[int, dict[str, Any]] = {}
        for row in lexical_rows:
            col_id = int(row.get("workspace_column_id") or 0)
            if col_id <= 0:
                continue
            by_col[col_id] = row

        vector_scores = self._load_vector_scores(
            workspace_id=workspace_id,
            source_record=source_record,
            domain_id=None,
            limit=max(limit * 6, 24),
        )

        missing_vector_ids = [col_id for col_id in vector_scores if col_id not in by_col]
        if missing_vector_ids:
            hydrated = self._load_candidates_by_ids(
                workspace_id=workspace_id,
                column_ids=missing_vector_ids,
                domain_id=None,
            )
            for row in hydrated:
                col_id = int(row.get("workspace_column_id") or 0)
                if col_id > 0:
                    by_col[col_id] = row

        scored: list[RetrievedCandidate] = []
        for col_id, row in by_col.items():
            lexical_score = self._lexical_score(source_record=source_record, candidate=row)
            vector_score = float(vector_scores.get(col_id, 0.0))
            stronger_signal = max(lexical_score, vector_score)
            weaker_signal = min(lexical_score, vector_score)
            combined = (stronger_signal * 0.7) + (weaker_signal * 0.3)
            scored.append(
                RetrievedCandidate(
                    column_id=col_id,
                    workspace_table_id=int(row.get("workspace_table_id") or 0),
                    column_name=str(row.get("column_name") or ""),
                    display_name=_display_name(str(row.get("column_name") or "")),
                    table_name=str(row.get("table_name") or ""),
                    domain_id=_to_int_or_none(row.get("domain_id")),
                    domain_name=_to_text_or_none(row.get("domain_name")),
                    description=_to_text_or_none(row.get("description")),
                    data_type=_to_text_or_none(row.get("data_type")),
                    semantic_type=_to_text_or_none(row.get("semantic_type")),
                    entity=_to_text_or_none(row.get("entity")),
                    preferred_domain_match=(
                        preferred_domain_id is not None and _to_int_or_none(row.get("domain_id")) == preferred_domain_id
                    ),
                    vector_score=vector_score,
                    lexical_score=lexical_score,
                    combined_retrieval_score=combined,
                )
            )

        scored.sort(key=lambda item: (item.combined_retrieval_score, item.lexical_score, item.vector_score), reverse=True)
        return [item.to_dict() for item in scored]

    def _load_lexical_candidates(
        self,
        *,
        workspace_id: str,
        source_record: SourceFieldRecord,
        domain_id: Optional[int],
        max_rows: int,
    ) -> List[Dict[str, Any]]:
        search_terms = _lexical_query_terms(source_record)[:10]
        source_name_norm = normalize_identifier(source_record.source_field_name)
        source_name_parts = split_identifier(source_record.source_field_name)
        source_name_compact = "".join(source_name_parts)
        source_name_phrase = " ".join(source_name_parts)

        params: Dict[str, Any] = {
            "workspace_id": workspace_id,
            "limit": int(max_rows),
            "domain_id": int(domain_id) if domain_id is not None else None,
            "source_name_norm": source_name_norm,
            "source_name_compact": source_name_compact,
            "source_name_phrase": source_name_phrase,
        }

        token_clause = ""
        lexical_score_parts = [
            "CASE WHEN LOWER(wc.column_name) = :source_name_norm THEN 240 ELSE 0 END",
            "CASE WHEN LOWER(REPLACE(REPLACE(wc.column_name, '_', ''), '-', '')) = :source_name_compact THEN 210 ELSE 0 END",
            "CASE WHEN LOWER(REPLACE(REPLACE(wc.column_name, '_', ' '), '-', ' ')) = :source_name_phrase THEN 190 ELSE 0 END",
        ]
        if search_terms:
            parts: list[str] = []
            for idx, term in enumerate(search_terms):
                key = f"term{idx}"
                params[key] = f"%{normalize_text(term)}%"
                parts.append(
                    f"(LOWER(wc.column_name) LIKE :{key} OR LOWER(COALESCE(wc.description, '')) LIKE :{key} "
                    f"OR LOWER(COALESCE(wt.table_name, '')) LIKE :{key} OR LOWER(COALESCE(wt.source_table_name, '')) LIKE :{key})"
                )
                lexical_score_parts.extend([
                    f"CASE WHEN LOWER(wc.column_name) LIKE :{key} THEN 28 ELSE 0 END",
                    f"CASE WHEN LOWER(COALESCE(wc.description, '')) LIKE :{key} THEN 16 ELSE 0 END",
                    f"CASE WHEN LOWER(COALESCE(wt.table_name, '')) LIKE :{key} OR LOWER(COALESCE(wt.source_table_name, '')) LIKE :{key} THEN 10 ELSE 0 END",
                ])
            token_clause = " AND (" + " OR ".join(parts) + ")"
        lexical_hit_score_sql = " + ".join(lexical_score_parts)

        rows = self._sql.execute_query_mappings(
            f"""
            SELECT
              wc.id AS workspace_column_id,
              wc.workspace_table_id,
              wc.column_name,
              wc.description,
              wc.data_type,
              wc.semantic_type,
              wc.semantic_entity AS entity,
              COALESCE(NULLIF(wt.source_table_name, ''), wt.table_name) AS table_name,
              (
                SELECT d.id
                FROM domain_workspace_table dwt
                JOIN domain d
                  ON d.id = dwt.domain_id
                 AND d.workspace_id = wt.workspace_id
                 AND d.is_active = 1
                WHERE dwt.workspace_table_id = wt.id
                ORDER BY dwt.is_primary DESC, dwt.sort_order ASC, d.id ASC
                LIMIT 1
              ) AS domain_id,
              (
                SELECT d.name
                FROM domain_workspace_table dwt
                JOIN domain d
                  ON d.id = dwt.domain_id
                 AND d.workspace_id = wt.workspace_id
                 AND d.is_active = 1
                WHERE dwt.workspace_table_id = wt.id
                ORDER BY dwt.is_primary DESC, dwt.sort_order ASC, d.id ASC
                LIMIT 1
              ) AS domain_name,
              ({lexical_hit_score_sql}) AS lexical_hit_score
            FROM workspace_column wc
            JOIN workspace_table wt ON wt.id = wc.workspace_table_id
            WHERE wt.workspace_id = :workspace_id
              AND (:domain_id IS NULL OR EXISTS (
                SELECT 1
                FROM domain_workspace_table dwt_filter
                WHERE dwt_filter.workspace_table_id = wt.id
                  AND dwt_filter.domain_id = :domain_id
              ))
              {token_clause}
            ORDER BY lexical_hit_score DESC, wc.id DESC
            LIMIT :limit
            """,
            params,
        )
        return rows

    def _load_candidates_by_ids(
        self,
        *,
        workspace_id: str,
        column_ids: List[int],
        domain_id: Optional[int],
    ) -> List[Dict[str, Any]]:
        clean_ids = sorted({int(v) for v in column_ids if int(v) > 0})
        if not clean_ids:
            return []

        params: Dict[str, Any] = {
            "workspace_id": workspace_id,
            "domain_id": int(domain_id) if domain_id is not None else None,
        }
        id_binds: list[str] = []
        for idx, col_id in enumerate(clean_ids):
            key = f"id{idx}"
            params[key] = col_id
            id_binds.append(f":{key}")

        return self._sql.execute_query_mappings(
            f"""
            SELECT
              wc.id AS workspace_column_id,
              wc.workspace_table_id,
              wc.column_name,
              wc.description,
              wc.data_type,
              wc.semantic_type,
              wc.semantic_entity AS entity,
              COALESCE(NULLIF(wt.source_table_name, ''), wt.table_name) AS table_name,
              (
                SELECT d.id
                FROM domain_workspace_table dwt
                JOIN domain d
                  ON d.id = dwt.domain_id
                 AND d.workspace_id = wt.workspace_id
                 AND d.is_active = 1
                WHERE dwt.workspace_table_id = wt.id
                ORDER BY dwt.is_primary DESC, dwt.sort_order ASC, d.id ASC
                LIMIT 1
              ) AS domain_id,
              (
                SELECT d.name
                FROM domain_workspace_table dwt
                JOIN domain d
                  ON d.id = dwt.domain_id
                 AND d.workspace_id = wt.workspace_id
                 AND d.is_active = 1
                WHERE dwt.workspace_table_id = wt.id
                ORDER BY dwt.is_primary DESC, dwt.sort_order ASC, d.id ASC
                LIMIT 1
              ) AS domain_name
            FROM workspace_column wc
            JOIN workspace_table wt ON wt.id = wc.workspace_table_id
            WHERE wt.workspace_id = :workspace_id
              AND wc.id IN ({', '.join(id_binds)})
              AND (:domain_id IS NULL OR EXISTS (
                SELECT 1
                FROM domain_workspace_table dwt_filter
                WHERE dwt_filter.workspace_table_id = wt.id
                  AND dwt_filter.domain_id = :domain_id
              ))
            """,
            params,
        )

    def _load_vector_scores(
        self,
        *,
        workspace_id: str,
        source_record: SourceFieldRecord,
        domain_id: Optional[int],
        limit: int,
    ) -> Dict[int, float]:
        if self._vector is None:
            return {}
        query_text = _vector_query_text(source_record)
        try:
            payload = self._vector.search(
                query=query_text,
                workspace_id=workspace_id,
                kinds=["column"],
                domain_id=int(domain_id) if domain_id is not None else None,
                limit=limit,
            )
        except VECTOR_RETRIEVAL_FALLBACK_ERRORS as exc:
            logger.warning("ForgeMatch vector retrieval failed: %s", exc)
            return {}

        scores: dict[int, float] = {}
        for row in ((payload.get("results") or {}).get("columns") or []):
            col_id = _to_int_or_none(row.get("workspaceColumnId"))
            if col_id is None:
                continue
            score = float(row.get("score") or 0.0)
            if score <= 0:
                continue
            prev = scores.get(col_id)
            if prev is None or score > prev:
                scores[col_id] = score
        return scores

    @staticmethod
    def _lexical_score(*, source_record: SourceFieldRecord, candidate: Dict[str, Any]) -> float:
        source_name = normalize_identifier(source_record.source_field_name)
        source_desc = normalize_text(source_record.source_description)
        source_object = normalize_identifier(source_record.source_object_name)
        source_tokens = _expanded_source_tokens(source_record)

        cand_name = normalize_identifier(candidate.get("column_name"))
        cand_desc = normalize_text(candidate.get("description"))
        cand_table = normalize_identifier(candidate.get("table_name"))
        candidate_tokens = token_set(candidate.get("column_name"), candidate.get("description"), candidate.get("table_name"))

        exact = 1.0 if source_name and source_name == cand_name else 0.0
        compact_exact = (
            1.0
            if source_name
            and source_name.replace("_", "") == cand_name.replace("_", "")
            else 0.0
        )
        seq_name = SequenceMatcher(None, source_name, cand_name).ratio() if source_name and cand_name else 0.0
        seq_desc = SequenceMatcher(None, source_desc, cand_desc).ratio() if source_desc and cand_desc else 0.0
        object_score = SequenceMatcher(None, source_object, cand_table).ratio() if source_object and cand_table else 0.0

        token_score = token_overlap_score(source_tokens, candidate_tokens)

        score = (
            (exact * 0.35)
            + (compact_exact * 0.20)
            + (seq_name * 0.22)
            + (token_score * 0.18)
            + (seq_desc * 0.10)
            + (object_score * 0.05)
        )
        return max(0.0, min(1.0, score))


def _expanded_source_tokens(source_record: SourceFieldRecord) -> set[str]:
    tokens = set(token_set(source_record.source_field_name, source_record.source_description, source_record.source_object_name))
    for term in _lexical_query_terms(source_record):
        norm = normalize_text(term)
        if norm:
            tokens.update(token_set(norm))
            compact = norm.replace(" ", "")
            if compact:
                tokens.add(compact)
    return {token for token in tokens if token}


def _lexical_query_terms(source_record: SourceFieldRecord) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()

    def _push(value: object) -> None:
        text = normalize_text(value)
        if not text or text in seen:
            return
        seen.add(text)
        out.append(text)

    name_parts = split_identifier(source_record.source_field_name)
    if name_parts:
        _push(" ".join(name_parts))
        _push("".join(name_parts))
        for part in name_parts:
            _push(part)

    for token in token_set(source_record.source_description, source_record.source_object_name):
        _push(token)

    name_key = " ".join(name_parts)
    token_key = set(name_parts)
    if {"birth", "date"} <= token_key:
        _push("date of birth")
        _push("dob")
    if {"first", "name"} <= token_key:
        _push("given name")
        _push("forename")
    if {"last", "name"} <= token_key:
        _push("family name")
        _push("surname")
    if name_key == "student id":
        _push("student identifier")
        _push("person id")

    return out


def _vector_query_text(source_record: SourceFieldRecord) -> str:
    parts: list[str] = []
    field_name = str(source_record.source_field_name or "").strip()
    if field_name:
        parts.append(field_name)

    alias_terms = _semantic_alias_terms(source_record)
    if alias_terms:
        parts.append("Aliases: " + ", ".join(alias_terms))

    if source_record.source_description:
        parts.append(str(source_record.source_description).strip())
    if source_record.source_object_name:
        parts.append(f"Object: {str(source_record.source_object_name).strip()}")
    if source_record.source_type:
        parts.append(f"Type: {str(source_record.source_type).strip()}")
    if source_record.sample_value:
        parts.append(f"Sample: {str(source_record.sample_value).strip()}")
    return ". ".join(part for part in parts if part)


def _semantic_alias_terms(source_record: SourceFieldRecord) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()

    def _push(value: object) -> None:
        text = normalize_text(value)
        if not text or text in seen:
            return
        seen.add(text)
        out.append(text)

    name_parts = split_identifier(source_record.source_field_name)
    token_key = set(name_parts).union(token_set(source_record.source_description))
    name_key = " ".join(name_parts)

    if {"birth", "date"} <= token_key or "birthday" in token_key:
        _push("birth date")
        _push("date of birth")
        _push("birthdate")
        _push("dob")
    if {"first", "name"} <= token_key or name_key == "firstname":
        _push("first name")
        _push("given name")
        _push("forename")
    if {"last", "name"} <= token_key or name_key == "lastname":
        _push("last name")
        _push("family name")
        _push("surname")
    if name_key == "student id":
        _push("student identifier")
        _push("person id")

    return out


def _display_name(column_name: str) -> str:
    clean = str(column_name or "").strip()
    if clean == "":
        return ""
    return " ".join(token.capitalize() for token in clean.replace("-", "_").split("_") if token)


def _to_text_or_none(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _to_int_or_none(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


class ForgeMatchColumnRetrievalAdapter:
    def __init__(self, *, owner: ForgeMatchCandidateRetriever) -> None:
        self._owner = owner

    def retrieve(self, *, context: PipelineContext) -> CandidateSetArtifact:
        source_record = context.request.get("source_record")
        if not isinstance(source_record, SourceFieldRecord):
            raise TypeError("ForgeMatchColumnRetrievalAdapter requires a SourceFieldRecord in request['source_record'].")

        rows = self._owner._retrieve_initial_candidates(
            workspace_id=str(context.workspace_id or "").strip(),
            source_record=source_record,
            top_n=int(context.request.get("top_n") or 8),
            preferred_domain_id=_to_int_or_none(
                context.request.get("preferred_domain_id") or context.request.get("domain_id")
            ),
        )
        return CandidateSetArtifact(
            candidates=[candidate_from_column_row(row) for row in rows],
            retrieval_debug={
                "candidate_count": len(rows),
                "preferred_domain_id": _to_int_or_none(
                    context.request.get("preferred_domain_id") or context.request.get("domain_id")
                ),
                "search_scope": "workspace_global",
            },
        )


__all__ = [
    "ForgeMatchCandidateRetriever",
    "ForgeMatchColumnRetrievalAdapter",
    "RetrievedCandidate",
]
