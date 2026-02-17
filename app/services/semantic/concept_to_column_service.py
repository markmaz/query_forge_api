from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from app.adapters.mysql_sql_executor import MySQLSQLExecutor
from app.ports.sql_executor import SQLExecutor


class ConceptToColumnService:
    def __init__(self, *, sql: Optional[SQLExecutor] = None) -> None:
        self._sql = sql or MySQLSQLExecutor()

    def map_concepts_to_columns(
        self,
        *,
        workspace_id: str,
        vertical_norm: str,
        concept_hits: Sequence[Dict[str, Any]],
        max_columns: int,
        domain_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        workspace = str(workspace_id or "").strip()
        vertical = _norm_vertical(vertical_norm)
        concepts = [str(hit.get("concept_key") or "").strip().upper() for hit in concept_hits]
        concepts = [c for c in concepts if c]

        if not workspace or not concepts:
            return {
                "concepts": concepts,
                "mapped_columns": [],
                "candidate_model_column_ids": [],
            }

        max_cols = max(1, min(500, int(max_columns or 60)))
        by_key: Dict[Tuple[int, str], Dict[str, Any]] = {}

        primary_rows = self._query_primary_assignments(
            workspace_id=workspace,
            concept_keys=concepts,
            domain_id=domain_id,
        )
        self._merge_rows(by_key, primary_rows)

        map_rows = self._query_relationship_map(
            workspace_id=workspace,
            vertical_norm=vertical,
            concept_keys=concepts,
            domain_id=domain_id,
        )
        self._merge_rows(by_key, map_rows)

        mapped_concepts = {str(row.get("concept_key") or "").strip().upper() for row in by_key.values()}
        missing_concepts = [c for c in concepts if c not in mapped_concepts]
        if missing_concepts:
            fallback_rows = self._fallback_by_alias(
                workspace_id=workspace,
                vertical_norm=vertical,
                concept_keys=missing_concepts,
                domain_id=domain_id,
            )
            self._merge_rows(by_key, fallback_rows)

        rows = list(by_key.values())
        rows.sort(key=lambda r: (float(r.get("weight") or 0.0), int(r.get("model_column_id") or 0)), reverse=True)
        rows = rows[:max_cols]

        candidate_ids = []
        seen = set()
        for row in rows:
            mid = int(row["model_column_id"])
            if mid in seen:
                continue
            seen.add(mid)
            candidate_ids.append(mid)

        return {
            "concepts": concepts,
            "mapped_columns": rows,
            "candidate_model_column_ids": candidate_ids,
        }

    def _query_primary_assignments(
        self,
        *,
        workspace_id: str,
        concept_keys: Sequence[str],
        domain_id: Optional[int],
    ) -> List[Dict[str, Any]]:
        in_sql, in_params = _in_clause("ck", concept_keys)
        params: Dict[str, Any] = {
            "workspace_id": workspace_id,
            **in_params,
        }
        domain_sql = ""
        if domain_id is not None:
            params["domain_id"] = int(domain_id)
            domain_sql = (
                """
                AND EXISTS (
                    SELECT 1
                    FROM domain_workspace_table dwt
                    WHERE dwt.domain_id = :domain_id
                      AND dwt.workspace_table_id = wt.id
                )
                """
            )

        return self._sql.execute_query_mappings(
            f"""
            SELECT DISTINCT
              mc.id AS model_column_id,
              wt.table_name,
              wc.column_name,
              mc.semantic_concept_key AS concept_key,
              1.0 AS weight
            FROM workspace_table wt
            JOIN workspace_column wc
              ON wc.workspace_table_id = wt.id
             AND wc.exists_in_dbx = 1
            JOIN model_column mc
              ON mc.model_table_id = wt.model_table_id
             AND mc.column_name = wc.column_name
            WHERE wt.workspace_id = :workspace_id
              AND wt.exists_in_dbx = 1
              AND mc.semantic_concept_key IN ({in_sql})
              {domain_sql}
            """,
            params,
        )

    def _query_relationship_map(
        self,
        *,
        workspace_id: str,
        vertical_norm: str,
        concept_keys: Sequence[str],
        domain_id: Optional[int],
    ) -> List[Dict[str, Any]]:
        in_sql, in_params = _in_clause("ck", concept_keys)
        params: Dict[str, Any] = {
            "workspace_id": workspace_id,
            "vertical_norm": vertical_norm,
            **in_params,
        }
        domain_sql = ""
        if domain_id is not None:
            params["domain_id"] = int(domain_id)
            domain_sql = (
                """
                AND EXISTS (
                    SELECT 1
                    FROM domain_workspace_table dwt
                    WHERE dwt.domain_id = :domain_id
                      AND dwt.workspace_table_id = wt.id
                )
                """
            )

        return self._sql.execute_query_mappings(
            f"""
            SELECT DISTINCT
              m.model_column_id,
              wt.table_name,
              wc.column_name,
              sc.concept_key,
              m.weight
            FROM model_column_semantic_concept_map m
            JOIN semantic_concept sc
              ON sc.id = m.semantic_concept_id
            JOIN model_column mc
              ON mc.id = m.model_column_id
            JOIN workspace_table wt
              ON wt.model_table_id = mc.model_table_id
             AND wt.workspace_id = :workspace_id
             AND wt.exists_in_dbx = 1
            JOIN workspace_column wc
              ON wc.workspace_table_id = wt.id
             AND wc.column_name = mc.column_name
             AND wc.exists_in_dbx = 1
            WHERE m.vertical_norm IN (:vertical_norm, 'generic')
              AND sc.concept_key IN ({in_sql})
              {domain_sql}
            """,
            params,
        )

    def _fallback_by_alias(
        self,
        *,
        workspace_id: str,
        vertical_norm: str,
        concept_keys: Sequence[str],
        domain_id: Optional[int],
    ) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for concept_key in concept_keys:
            aliases = self._sql.execute_query_mappings(
                """
                SELECT alias_key
                FROM semantic_concept_alias
                WHERE vertical_norm IN (:vertical_norm, 'generic')
                  AND concept_key = :concept_key
                ORDER BY weight DESC
                LIMIT 8
                """,
                {"vertical_norm": vertical_norm, "concept_key": concept_key},
            )
            tokens = [str(row.get("alias_key") or "").strip().lower() for row in aliases]
            tokens = [tok for tok in tokens if tok]
            if not tokens:
                continue

            like_parts: List[str] = []
            params: Dict[str, Any] = {
                "workspace_id": workspace_id,
                "concept_key": concept_key,
            }
            for idx, token in enumerate(tokens):
                key = f"tok{idx}"
                params[key] = f"%{token}%"
                like_parts.append(f"LOWER(mc.column_name) LIKE :{key}")
                like_parts.append(f"LOWER(COALESCE(mc.description, '')) LIKE :{key}")

            domain_sql = ""
            if domain_id is not None:
                params["domain_id"] = int(domain_id)
                domain_sql = (
                    """
                    AND EXISTS (
                        SELECT 1
                        FROM domain_workspace_table dwt
                        WHERE dwt.domain_id = :domain_id
                          AND dwt.workspace_table_id = wt.id
                    )
                    """
                )

            rows = self._sql.execute_query_mappings(
                f"""
                SELECT DISTINCT
                  mc.id AS model_column_id,
                  wt.table_name,
                  wc.column_name,
                  :concept_key AS concept_key,
                  0.35 AS weight
                FROM workspace_table wt
                JOIN workspace_column wc
                  ON wc.workspace_table_id = wt.id
                 AND wc.exists_in_dbx = 1
                JOIN model_column mc
                  ON mc.model_table_id = wt.model_table_id
                 AND mc.column_name = wc.column_name
                WHERE wt.workspace_id = :workspace_id
                  AND wt.exists_in_dbx = 1
                  AND ({' OR '.join(like_parts)})
                  {domain_sql}
                LIMIT 20
                """,
                params,
            )
            out.extend(rows)

        return out

    @staticmethod
    def _merge_rows(by_key: Dict[Tuple[int, str], Dict[str, Any]], rows: Iterable[Dict[str, Any]]) -> None:
        for row in rows:
            try:
                model_column_id = int(row.get("model_column_id"))
            except Exception:
                continue
            concept_key = str(row.get("concept_key") or "").strip().upper()
            if concept_key == "":
                continue
            weight = float(row.get("weight") or 0.0)
            key = (model_column_id, concept_key)
            existing = by_key.get(key)
            if existing is not None and float(existing.get("weight") or 0.0) >= weight:
                continue
            by_key[key] = {
                "model_column_id": model_column_id,
                "table_name": row.get("table_name"),
                "column_name": row.get("column_name"),
                "concept_key": concept_key,
                "weight": round(weight, 4),
            }


def _in_clause(prefix: str, values: Sequence[str]) -> Tuple[str, Dict[str, Any]]:
    params: Dict[str, Any] = {}
    keys: List[str] = []
    for idx, value in enumerate(values):
        name = f"{prefix}{idx}"
        keys.append(f":{name}")
        params[name] = str(value)
    return ", ".join(keys) if keys else "NULL", params


def _norm_vertical(value: str) -> str:
    text = str(value or "generic").strip().lower()
    return text or "generic"


__all__ = ["ConceptToColumnService"]
