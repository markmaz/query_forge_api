from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.ports.sql_executor import ForgeQueryPort
from app.services.semantic.vertical_norm import normalize_semantic_vertical


class ConceptToColumnService:
    PER_CONCEPT_LIMIT = 3

    def __init__(self, *, sql: Optional[ForgeQueryPort] = None) -> None:
        self._sql = sql or ForgeMetaSQL()

    def map_concepts_to_columns(
        self,
        *,
        workspace_id: str,
        vertical_norm: Optional[str] = None,
        concept_hits: Sequence[Dict[str, Any]],
        max_columns: int,
        domain_id: Optional[int] = None,
        intent_entity: Optional[str] = None,
    ) -> Dict[str, Any]:
        workspace = str(workspace_id or "").strip()
        vertical = _norm_vertical(vertical_norm)
        concepts = [str(hit.get("concept_key") or "").strip().upper() for hit in concept_hits]
        concepts = [c for c in concepts if c]

        if not workspace or not concepts:
            return {
                "concepts": concepts,
                "mapped_columns": [],
                "candidate_workspace_column_ids": [],
                "candidate_model_column_ids": [],
                "ranked_candidates_by_concept": {},
                "warnings": [],
            }

        max_cols = max(1, min(500, int(max_columns or 60)))
        ranked_m2m = self._query_ranked_m2m(
            workspace_id=workspace,
            vertical_norm=vertical,
            concept_keys=concepts,
            domain_id=domain_id,
            per_concept_limit=self.PER_CONCEPT_LIMIT,
        )

        mapped_concepts = {str(row.get("concept_key") or "").strip().upper() for row in ranked_m2m}
        missing_concepts = [c for c in concepts if c not in mapped_concepts]
        ranked_fallback: List[Dict[str, Any]] = []
        if missing_concepts:
            ranked_fallback = self._query_ranked_primary_fallback(
                workspace_id=workspace,
                vertical_norm=vertical,
                concept_keys=missing_concepts,
                domain_id=domain_id,
                per_concept_limit=self.PER_CONCEPT_LIMIT,
            )

        concept_order = {key: idx for idx, key in enumerate(concepts)}
        rows = list(ranked_m2m) + list(ranked_fallback)
        rows = self._apply_entity_intent_reranking(rows=rows, intent_entity=intent_entity)
        rows.sort(
            key=lambda r: (
                concept_order.get(str(r.get("concept_key") or "").upper(), len(concepts)),
                -float(r.get("effective_weight") or r.get("final_score") or 0.0),
                -float(r.get("base_weight") or 0.0),
                int(r.get("workspace_column_id") or r.get("model_column_id") or 0),
            )
        )
        rows = rows[: max(max_cols, len(concepts) * self.PER_CONCEPT_LIMIT)]
        rows, mapping_warnings = self._apply_mapping_guardrails(rows=rows, concepts=concepts)
        mapping_warnings.extend(
            self._build_intent_mismatch_warnings(rows=rows, intent_entity=intent_entity)
        )

        candidate_workspace_ids: List[int] = []
        seen_workspace = set()
        candidate_model_ids: List[int] = []
        seen_model = set()
        for row in rows:
            wid = _to_int_or_none(row.get("workspace_column_id"))
            if wid is not None and wid not in seen_workspace:
                seen_workspace.add(wid)
                candidate_workspace_ids.append(wid)
            mid = _to_int_or_none(row.get("model_column_id"))
            if mid is not None and mid not in seen_model:
                seen_model.add(mid)
                candidate_model_ids.append(mid)

        ranked_by_concept: Dict[str, List[Dict[str, Any]]] = {}
        for row in rows:
            concept_key = str(row.get("concept_key") or "").strip().upper()
            if concept_key == "":
                continue
            ranked_by_concept.setdefault(concept_key, []).append(dict(row))

        return {
            "concepts": concepts,
            "mapped_columns": rows,
            "candidate_workspace_column_ids": candidate_workspace_ids,
            "candidate_model_column_ids": candidate_model_ids,
            "ranked_candidates_by_concept": ranked_by_concept,
            "warnings": mapping_warnings,
        }

    def _query_ranked_m2m(
        self,
        *,
        workspace_id: str,
        vertical_norm: str,
        concept_keys: Sequence[str],
        domain_id: Optional[int],
        per_concept_limit: int,
    ) -> List[Dict[str, Any]]:
        if not concept_keys:
            return []
        in_sql, in_params = _in_clause("ck", concept_keys)
        params: Dict[str, Any] = {
            "workspace_id": workspace_id,
            "vertical_norm": vertical_norm,
            "per_concept_limit": max(1, int(per_concept_limit or self.PER_CONCEPT_LIMIT)),
            **in_params,
        }
        domain_join = ""
        if domain_id is not None:
            params["domain_id"] = int(domain_id)
            domain_join = (
                """
                JOIN domain_workspace_table dwt
                  ON dwt.workspace_table_id = wt.id
                 AND dwt.domain_id = :domain_id
                """
            )

        rows = self._sql.execute_query_mappings(
            f"""
            WITH alias_ranked AS (
              SELECT
                a.concept_key,
                LOWER(a.alias_key) AS alias_key_lc,
                ROW_NUMBER() OVER (
                  PARTITION BY a.concept_key
                  ORDER BY
                    CASE WHEN a.vertical_norm = :vertical_norm THEN 0 ELSE 1 END,
                    a.weight DESC,
                    a.id ASC
                ) AS rn_alias
              FROM semantic_concept_alias a
              WHERE a.vertical_norm IN (:vertical_norm, 'generic')
                AND a.concept_key IN ({in_sql})
            ),
            alias_top AS (
              SELECT concept_key, alias_key_lc
              FROM alias_ranked
              WHERE rn_alias <= 8
            ),
            scored AS (
              SELECT
                wc.id AS workspace_column_id,
                wt.id AS workspace_table_id,
                COALESCE(NULLIF(wt.source_table_name, ''), wt.table_name) AS table_name,
                wc.column_name,
                sc.concept_key,
                wc.semantic_concept_key AS authoritative_concept_key,
                sc.entity,
                sc.semantic_type,
                m.weight AS base_weight,
                CASE WHEN LOWER(COALESCE(NULLIF(wt.source_table_name, ''), wt.table_name)) = 'dim_student' AND LOWER(COALESCE(sc.entity, '')) = 'student' THEN 2.0 ELSE 0.0 END AS entity_bonus,
                CASE WHEN LOWER(COALESCE(NULLIF(wt.source_table_name, ''), wt.table_name)) LIKE 'dim\\_%' ESCAPE '\\\\' THEN 1.0 ELSE 0.0 END AS dim_bonus,
                CASE
                  WHEN LOWER(COALESCE(NULLIF(wt.source_table_name, ''), wt.table_name)) LIKE 'fct\\_%' ESCAPE '\\\\'
                   AND LOWER(COALESCE(sc.semantic_type, '')) IN ('attribute', 'flag')
                  THEN -0.5
                  ELSE 0.0
                END AS fact_penalty,
                CASE
                  WHEN EXISTS (
                    SELECT 1
                    FROM alias_top at
                    WHERE at.concept_key COLLATE utf8mb4_0900_ai_ci
                      = sc.concept_key COLLATE utf8mb4_0900_ai_ci
                      AND at.alias_key_lc COLLATE utf8mb4_unicode_ci
                        = LOWER(wc.column_name) COLLATE utf8mb4_unicode_ci
                  )
                  THEN 0.5
                  ELSE 0.0
                END AS alias_bonus,
                CASE
                  WHEN wc.semantic_concept_key IS NULL OR TRIM(wc.semantic_concept_key) = '' THEN 0.0
                  WHEN wc.semantic_concept_key COLLATE utf8mb4_0900_ai_ci
                    = sc.concept_key COLLATE utf8mb4_0900_ai_ci THEN 0.75
                  ELSE -0.75
                END AS authoritative_bonus,
                CASE
                  WHEN wc.semantic_concept_key IS NULL OR TRIM(wc.semantic_concept_key) = '' THEN 0
                  WHEN wc.semantic_concept_key COLLATE utf8mb4_0900_ai_ci
                    = sc.concept_key COLLATE utf8mb4_0900_ai_ci THEN 1
                  ELSE 0
                END AS authoritative_match
              FROM workspace_column_semantic_concept_map m
              JOIN semantic_concept sc
                ON sc.id = m.semantic_concept_id
              JOIN workspace_column wc
                ON wc.id = m.workspace_column_id
               AND wc.exists_in_dbx = 1
              JOIN workspace_table wt
                ON wt.id = wc.workspace_table_id
               AND wt.workspace_id = :workspace_id
               AND wt.exists_in_dbx = 1
              {domain_join}
              WHERE m.vertical_norm IN (:vertical_norm, 'generic')
                AND sc.concept_key IN ({in_sql})
            ),
            dedup AS (
              SELECT
                scored.*,
                (
                  scored.base_weight
                  + scored.entity_bonus
                  + scored.dim_bonus
                  + scored.fact_penalty
                  + scored.alias_bonus
                  + scored.authoritative_bonus
                ) AS final_score,
                ROW_NUMBER() OVER (
                  PARTITION BY scored.concept_key, scored.workspace_column_id
                  ORDER BY
                    (
                      scored.base_weight
                      + scored.entity_bonus
                      + scored.dim_bonus
                      + scored.fact_penalty
                      + scored.alias_bonus
                      + scored.authoritative_bonus
                    ) DESC,
                    scored.workspace_table_id ASC
                ) AS rn_model
              FROM scored
            ),
            ranked AS (
              SELECT
                dedup.*,
                ROW_NUMBER() OVER (
                  PARTITION BY dedup.concept_key
                  ORDER BY dedup.final_score DESC, dedup.workspace_column_id ASC
                ) AS rn
              FROM dedup
              WHERE dedup.rn_model = 1
            )
            SELECT
              ranked.workspace_column_id,
              ranked.workspace_table_id,
              ranked.table_name,
              ranked.column_name,
              ranked.concept_key,
              ranked.authoritative_concept_key,
              ranked.base_weight AS weight,
              ranked.base_weight,
              ranked.entity_bonus,
              ranked.dim_bonus,
              ranked.fact_penalty,
              ranked.alias_bonus,
              ranked.authoritative_bonus,
              ranked.authoritative_match,
              ranked.entity,
              ranked.semantic_type,
              ranked.final_score,
              'm2m' AS source
            FROM ranked
            WHERE ranked.rn <= :per_concept_limit
            ORDER BY ranked.concept_key, ranked.rn
            """,
            params,
        )
        return [self._normalize_scored_row(row) for row in rows]

    def _query_ranked_primary_fallback(
        self,
        *,
        workspace_id: str,
        vertical_norm: str,
        concept_keys: Sequence[str],
        domain_id: Optional[int],
        per_concept_limit: int,
    ) -> List[Dict[str, Any]]:
        if not concept_keys:
            return []
        in_sql, in_params = _in_clause("ck", concept_keys)
        params: Dict[str, Any] = {
            "workspace_id": workspace_id,
            "vertical_norm": vertical_norm,
            "per_concept_limit": max(1, int(per_concept_limit or self.PER_CONCEPT_LIMIT)),
            **in_params,
        }
        domain_join = ""
        if domain_id is not None:
            params["domain_id"] = int(domain_id)
            domain_join = (
                """
                JOIN domain_workspace_table dwt
                  ON dwt.workspace_table_id = wt.id
                 AND dwt.domain_id = :domain_id
                """
            )

        rows = self._sql.execute_query_mappings(
            f"""
            WITH alias_ranked AS (
              SELECT
                a.concept_key,
                LOWER(a.alias_key) AS alias_key_lc,
                ROW_NUMBER() OVER (
                  PARTITION BY a.concept_key
                  ORDER BY
                    CASE WHEN a.vertical_norm = :vertical_norm THEN 0 ELSE 1 END,
                    a.weight DESC,
                    a.id ASC
                ) AS rn_alias
              FROM semantic_concept_alias a
              WHERE a.vertical_norm IN (:vertical_norm, 'generic')
                AND a.concept_key IN ({in_sql})
            ),
            alias_top AS (
              SELECT concept_key, alias_key_lc
              FROM alias_ranked
              WHERE rn_alias <= 8
            ),
            concept_ranked AS (
              SELECT
                sc.id,
                sc.concept_key,
                sc.semantic_type,
                sc.entity,
                ROW_NUMBER() OVER (
                  PARTITION BY sc.concept_key
                  ORDER BY
                    CASE WHEN sc.vertical_norm = :vertical_norm THEN 0 ELSE 1 END,
                    sc.id ASC
                ) AS rn_concept
              FROM semantic_concept sc
              WHERE sc.concept_key IN ({in_sql})
                AND sc.vertical_norm IN (:vertical_norm, 'generic')
            ),
            scored AS (
              SELECT
                wc.id AS workspace_column_id,
                wt.id AS workspace_table_id,
                COALESCE(NULLIF(wt.source_table_name, ''), wt.table_name) AS table_name,
                wc.column_name,
                cr.concept_key,
                cr.entity,
                cr.semantic_type,
                wc.semantic_concept_key AS authoritative_concept_key,
                1.0 AS base_weight,
                CASE WHEN LOWER(COALESCE(NULLIF(wt.source_table_name, ''), wt.table_name)) = 'dim_student' AND LOWER(COALESCE(cr.entity, '')) = 'student' THEN 2.0 ELSE 0.0 END AS entity_bonus,
                CASE WHEN LOWER(COALESCE(NULLIF(wt.source_table_name, ''), wt.table_name)) LIKE 'dim\\_%' ESCAPE '\\\\' THEN 1.0 ELSE 0.0 END AS dim_bonus,
                CASE
                  WHEN LOWER(COALESCE(NULLIF(wt.source_table_name, ''), wt.table_name)) LIKE 'fct\\_%' ESCAPE '\\\\'
                   AND LOWER(COALESCE(cr.semantic_type, '')) IN ('attribute', 'flag')
                  THEN -0.5
                  ELSE 0.0
                END AS fact_penalty,
                CASE
                  WHEN EXISTS (
                    SELECT 1
                    FROM alias_top at
                    WHERE at.concept_key COLLATE utf8mb4_0900_ai_ci
                      = cr.concept_key COLLATE utf8mb4_0900_ai_ci
                      AND at.alias_key_lc COLLATE utf8mb4_unicode_ci
                        = LOWER(wc.column_name) COLLATE utf8mb4_unicode_ci
                  )
                  THEN 0.5
                  ELSE 0.0
                END AS alias_bonus,
                0.75 AS authoritative_bonus,
                1 AS authoritative_match
              FROM workspace_column wc
              JOIN workspace_table wt
                ON wt.id = wc.workspace_table_id
               AND wt.workspace_id = :workspace_id
               AND wt.exists_in_dbx = 1
              JOIN concept_ranked cr
                ON cr.concept_key COLLATE utf8mb4_0900_ai_ci
                 = wc.semantic_concept_key COLLATE utf8mb4_0900_ai_ci
               AND cr.rn_concept = 1
              {domain_join}
              WHERE wc.exists_in_dbx = 1
                AND wc.semantic_concept_key IN ({in_sql})
            ),
            dedup AS (
              SELECT
                scored.*,
                (
                  scored.base_weight
                  + scored.entity_bonus
                  + scored.dim_bonus
                  + scored.fact_penalty
                  + scored.alias_bonus
                  + scored.authoritative_bonus
                ) AS final_score,
                ROW_NUMBER() OVER (
                  PARTITION BY scored.concept_key, scored.workspace_column_id
                  ORDER BY
                    (
                      scored.base_weight
                      + scored.entity_bonus
                      + scored.dim_bonus
                      + scored.fact_penalty
                      + scored.alias_bonus
                      + scored.authoritative_bonus
                    ) DESC,
                    scored.workspace_table_id ASC
                ) AS rn_model
              FROM scored
            ),
            ranked AS (
              SELECT
                dedup.*,
                ROW_NUMBER() OVER (
                  PARTITION BY dedup.concept_key
                  ORDER BY dedup.final_score DESC, dedup.workspace_column_id ASC
                ) AS rn
              FROM dedup
              WHERE dedup.rn_model = 1
            )
            SELECT
              ranked.workspace_column_id,
              ranked.workspace_table_id,
              ranked.table_name,
              ranked.column_name,
              ranked.concept_key,
              ranked.authoritative_concept_key,
              ranked.base_weight AS weight,
              ranked.base_weight,
              ranked.entity_bonus,
              ranked.dim_bonus,
              ranked.fact_penalty,
              ranked.alias_bonus,
              ranked.authoritative_bonus,
              ranked.authoritative_match,
              ranked.entity,
              ranked.semantic_type,
              ranked.final_score,
              'fallback_primary' AS source
            FROM ranked
            WHERE ranked.rn <= :per_concept_limit
            ORDER BY ranked.concept_key, ranked.rn
            """,
            params,
        )
        return [self._normalize_scored_row(row) for row in rows]

    @staticmethod
    def _normalize_scored_row(row: Dict[str, Any]) -> Dict[str, Any]:
        concept_key = str(row.get("concept_key") or "").strip().upper()
        weight = _to_float_or_none(row.get("weight"))
        base_weight = _to_float_or_none(row.get("base_weight"))
        entity_bonus = _to_float_or_none(row.get("entity_bonus"))
        dim_bonus = _to_float_or_none(row.get("dim_bonus"))
        fact_penalty = _to_float_or_none(row.get("fact_penalty"))
        alias_bonus = _to_float_or_none(row.get("alias_bonus"))
        authoritative_bonus = _to_float_or_none(row.get("authoritative_bonus"))
        authoritative_match = _to_int_or_none(row.get("authoritative_match"))
        final_score = _to_float_or_none(row.get("final_score"))
        base_weight_value = round(float(base_weight or 0.0), 4)
        return {
            "workspace_column_id": _to_int_or_none(row.get("workspace_column_id")),
            "model_column_id": _to_int_or_none(row.get("workspace_column_id")),
            "workspace_table_id": _to_int_or_none(row.get("workspace_table_id")),
            "table_name": row.get("table_name"),
            "column_name": row.get("column_name"),
            "model_table_name": row.get("table_name"),
            "concept_key": concept_key,
            "entity": str(row.get("entity") or "").strip().lower() or None,
            "semantic_type": str(row.get("semantic_type") or "").strip().lower() or None,
            "authoritative_concept_key": str(row.get("authoritative_concept_key") or "").strip().upper() or None,
            "weight": round(float(weight or 0.0), 4),
            "base_weight": base_weight_value,
            "entity_bonus": round(float(entity_bonus or 0.0), 4),
            "dim_bonus": round(float(dim_bonus or 0.0), 4),
            "fact_penalty": round(float(fact_penalty or 0.0), 4),
            "alias_bonus": round(float(alias_bonus or 0.0), 4),
            "authoritative_bonus": round(float(authoritative_bonus or 0.0), 4),
            "authoritative_match": bool(int(authoritative_match or 0)),
            "final_score": round(float(final_score or 0.0), 4),
            "entity_factor": 1.0,
            "table_factor": 1.0,
            "effective_weight": base_weight_value,
            "source": str(row.get("source") or "").strip().lower() or "m2m",
        }

    def _apply_mapping_guardrails(
        self,
        *,
        rows: Sequence[Dict[str, Any]],
        concepts: Sequence[str],
    ) -> Tuple[List[Dict[str, Any]], List[str]]:
        warnings: List[str] = []
        filtered: List[Dict[str, Any]] = []
        for row in rows:
            concept_key = str(row.get("concept_key") or "").strip().upper()
            column_name = str(row.get("column_name") or "").strip().lower()
            if concept_key == "":
                continue
            if (("race" in column_name) or ("ethnic" in column_name)) and concept_key == "CITY":
                warnings.append(
                    f"rejected_mapping_conflict concept=CITY column={column_name} reason=race_ethnic_to_city_denied"
                )
                continue
            if re.search(r"(^|[_\\W])city($|[_\\W])", column_name) and concept_key == "RACE":
                warnings.append(
                    f"rejected_mapping_conflict concept=RACE column={column_name} reason=city_to_race_denied"
                )
                continue
            filtered.append(dict(row))

        by_concept: Dict[str, List[Dict[str, Any]]] = {}
        for row in filtered:
            concept_key = str(row.get("concept_key") or "").strip().upper()
            if concept_key == "":
                continue
            by_concept.setdefault(concept_key, []).append(row)

        final_rows: List[Dict[str, Any]] = []
        for concept_key in concepts:
            key = str(concept_key or "").strip().upper()
            concept_rows = list(by_concept.get(key) or [])
            if not concept_rows:
                continue

            authoritative_rows = [row for row in concept_rows if bool(row.get("authoritative_match"))]
            if authoritative_rows:
                dropped = [row for row in concept_rows if not bool(row.get("authoritative_match"))]
                for row in dropped:
                    auth_key = str(row.get("authoritative_concept_key") or "").strip().upper()
                    if auth_key:
                        warnings.append(
                            f"authoritative_mapping_preferred concept={key} column={row.get('column_name')} authoritative={auth_key}"
                        )
                concept_rows = authoritative_rows

            concept_rows.sort(
                key=lambda r: (
                    -float(r.get("effective_weight") or r.get("final_score") or 0.0),
                    -float(r.get("base_weight") or 0.0),
                    int(r.get("workspace_column_id") or r.get("model_column_id") or 0),
                )
            )
            final_rows.extend(concept_rows[: self.PER_CONCEPT_LIMIT])

        return final_rows, warnings

    def _apply_entity_intent_reranking(
        self,
        *,
        rows: Sequence[Dict[str, Any]],
        intent_entity: Optional[str],
    ) -> List[Dict[str, Any]]:
        intent = _norm_entity(intent_entity)
        if intent is None:
            return [dict(row) for row in rows]

        out: List[Dict[str, Any]] = []
        for raw_row in rows:
            row = dict(raw_row)
            concept_key = str(row.get("concept_key") or "").strip().upper()
            concept_entity = _norm_entity(row.get("entity"))
            entity_factor = self._entity_factor(
                intent_entity=intent,
                concept_key=concept_key,
                concept_entity=concept_entity,
            )

            table_name = str(row.get("table_name") or row.get("model_table_name") or "").strip().lower()
            table_factor = self._table_factor(
                intent_entity=intent,
                table_name=table_name,
                is_name_concept=self._is_name_concept(row),
            )
            base_weight = _to_float_or_none(row.get("base_weight"))
            if base_weight is None:
                base_weight = _to_float_or_none(row.get("weight")) or 0.0
            effective_weight = max(0.0, float(base_weight) * entity_factor * table_factor)
            row["entity_factor"] = round(entity_factor, 4)
            row["table_factor"] = round(table_factor, 4)
            row["effective_weight"] = round(effective_weight, 4)
            out.append(row)
        return out

    @staticmethod
    def _entity_factor(*, intent_entity: str, concept_key: str, concept_entity: Optional[str]) -> float:
        key = str(concept_key or "").strip().upper()
        entity = _norm_entity(concept_entity)
        factor = 1.0
        if entity == intent_entity:
            factor = 1.4
        elif entity is not None and entity != intent_entity:
            factor = 0.7

        if intent_entity == "student":
            if key in {"STUDENT_FIRST_NAME", "STUDENT_LAST_NAME", "STUDENT_MIDDLE_NAME"}:
                return max(factor, 1.6)
            if key in {"FIRST_NAME", "LAST_NAME", "MIDDLE_NAME"}:
                return min(factor, 0.85)
            if key.startswith("STAFF_") and "NAME" in key:
                return min(factor, 0.5)
            if key.startswith("PARENT_") and "NAME" in key:
                return min(factor, 0.5)
        return factor

    @staticmethod
    def _is_name_concept(row: Dict[str, Any]) -> bool:
        concept_key = str(row.get("concept_key") or "").strip().upper()
        semantic_type = str(row.get("semantic_type") or "").strip().lower()
        if any(token in concept_key for token in ("FIRST_NAME", "LAST_NAME", "MIDDLE_NAME")):
            return True
        if "NAME" in concept_key and semantic_type == "identifier":
            return True
        return False

    @staticmethod
    def _table_factor(*, intent_entity: str, table_name: str, is_name_concept: bool) -> float:
        table = str(table_name or "").strip().lower()
        if table == "":
            return 1.0

        def _matches(prefix: str) -> bool:
            return table.startswith(prefix)

        if intent_entity == "student":
            if table in {"dim_student", "dim_student_school"} or _matches("fct_student_") or _matches("msr_student_"):
                return 1.25
            if is_name_concept and (_matches("dim_staff") or _matches("fct_staff_") or _matches("msr_staff_") or _matches("dim_parent") or _matches("fct_parent_") or _matches("msr_parent_")):
                return 0.65
            return 1.0

        if intent_entity == "staff":
            if table in {"dim_staff", "dim_staff_school"} or _matches("fct_staff_") or _matches("msr_staff_"):
                return 1.25
            if is_name_concept and (_matches("dim_student") or _matches("fct_student_") or _matches("msr_student_") or _matches("dim_parent") or _matches("fct_parent_") or _matches("msr_parent_")):
                return 0.65
            return 1.0

        if intent_entity == "parent":
            if table in {"dim_parent", "dim_parent_school"} or _matches("fct_parent_") or _matches("msr_parent_"):
                return 1.25
            if is_name_concept and (_matches("dim_student") or _matches("fct_student_") or _matches("msr_student_") or _matches("dim_staff") or _matches("fct_staff_") or _matches("msr_staff_")):
                return 0.65
            return 1.0
        return 1.0

    @staticmethod
    def _build_intent_mismatch_warnings(
        *,
        rows: Sequence[Dict[str, Any]],
        intent_entity: Optional[str],
    ) -> List[str]:
        intent = _norm_entity(intent_entity)
        if intent is None:
            return []
        top_rows = list(rows)[:6]
        if not top_rows:
            return []
        mismatch = 0
        evaluated = 0
        for row in top_rows:
            entity = _norm_entity(row.get("entity"))
            if entity is None:
                continue
            evaluated += 1
            if entity != intent:
                mismatch += 1
        if evaluated >= 3 and mismatch / float(evaluated) >= 0.66:
            return [f"intent_entity_mismatch intent={intent} top_rows={len(top_rows)} mismatched={mismatch}"]
        return []


def _in_clause(prefix: str, values: Sequence[str]) -> Tuple[str, Dict[str, Any]]:
    params: Dict[str, Any] = {}
    keys: List[str] = []
    for idx, value in enumerate(values):
        name = f"{prefix}{idx}"
        keys.append(f":{name}")
        params[name] = str(value)
    return ", ".join(keys) if keys else "NULL", params


def _norm_vertical(value: str) -> str:
    return normalize_semantic_vertical(value)


def _norm_entity(value: Any) -> Optional[str]:
    text = str(value or "").strip().lower()
    if text in {"student", "staff", "parent"}:
        return text
    return None


def _to_int_or_none(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _to_float_or_none(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


__all__ = ["ConceptToColumnService"]
