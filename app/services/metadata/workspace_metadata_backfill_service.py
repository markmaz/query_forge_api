from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.exceptions.forge_error import ForgeError
from app.ports.sql_executor import ForgeQueryPort

_TABLE_SCOPE_COUNTS_QUERY = """
/* qf_backfill:table_scope_counts */
SELECT
  COUNT(*) AS workspace_table_rows,
  SUM(CASE WHEN mt.id IS NOT NULL THEN 1 ELSE 0 END) AS matched_model_table_rows,
  SUM(CASE WHEN wt.model_table_id IS NOT NULL AND mt.id IS NULL THEN 1 ELSE 0 END) AS missing_model_table_rows
FROM workspace_table wt
LEFT JOIN model_table mt
  ON mt.id = wt.model_table_id
WHERE wt.model_table_id IS NOT NULL
  AND (:workspace_id IS NULL OR wt.workspace_id = :workspace_id)
"""

_TABLE_MISMATCH_COUNT_QUERY = """
/* qf_backfill:table_mismatch_count */
SELECT
  COUNT(*) AS mismatch_count
FROM workspace_table wt
JOIN model_table mt
  ON mt.id = wt.model_table_id
WHERE wt.model_table_id IS NOT NULL
  AND (:workspace_id IS NULL OR wt.workspace_id = :workspace_id)
  AND (
    COALESCE(wt.source_table_name, '') <> COALESCE(mt.source_table_name, '') OR
    COALESCE(wt.description, '') <> COALESCE(mt.description, '') OR
    COALESCE(wt.origin, '') <> COALESCE(mt.origin, '') OR
    COALESCE(wt.is_missing_in_source, 0) <> COALESCE(mt.is_missing_in_source, 0)
  )
"""

_TABLE_MISMATCH_SAMPLE_QUERY = """
/* qf_backfill:table_mismatch_samples */
SELECT
  wt.id AS workspace_table_id,
  wt.workspace_id,
  wt.model_table_id,
  wt.table_name,
  wt.source_table_name AS workspace_source_table_name,
  mt.source_table_name AS model_source_table_name,
  wt.origin AS workspace_origin,
  mt.origin AS model_origin
FROM workspace_table wt
JOIN model_table mt
  ON mt.id = wt.model_table_id
WHERE wt.model_table_id IS NOT NULL
  AND (:workspace_id IS NULL OR wt.workspace_id = :workspace_id)
  AND (
    COALESCE(wt.source_table_name, '') <> COALESCE(mt.source_table_name, '') OR
    COALESCE(wt.description, '') <> COALESCE(mt.description, '') OR
    COALESCE(wt.origin, '') <> COALESCE(mt.origin, '') OR
    COALESCE(wt.is_missing_in_source, 0) <> COALESCE(mt.is_missing_in_source, 0)
  )
ORDER BY wt.id
LIMIT :sample_limit
"""

_TABLE_UPDATE_QUERY = """
/* qf_backfill:table_update */
UPDATE workspace_table wt
JOIN model_table mt
  ON mt.id = wt.model_table_id
SET
  wt.source_table_name = mt.source_table_name,
  wt.description = mt.description,
  wt.origin = mt.origin,
  wt.is_missing_in_source = COALESCE(mt.is_missing_in_source, 0),
  wt.metadata_synced_at = CURRENT_TIMESTAMP,
  wt.metadata_updated_at = CURRENT_TIMESTAMP
WHERE wt.model_table_id IS NOT NULL
  AND (:workspace_id IS NULL OR wt.workspace_id = :workspace_id)
  AND (
    COALESCE(wt.source_table_name, '') <> COALESCE(mt.source_table_name, '') OR
    COALESCE(wt.description, '') <> COALESCE(mt.description, '') OR
    COALESCE(wt.origin, '') <> COALESCE(mt.origin, '') OR
    COALESCE(wt.is_missing_in_source, 0) <> COALESCE(mt.is_missing_in_source, 0)
  )
"""

_COLUMN_SCOPE_COUNTS_QUERY = """
/* qf_backfill:column_scope_counts */
SELECT
  COUNT(*) AS workspace_column_rows,
  SUM(CASE WHEN mc.id IS NOT NULL THEN 1 ELSE 0 END) AS matched_model_column_rows,
  SUM(CASE WHEN mc.id IS NULL THEN 1 ELSE 0 END) AS missing_model_column_rows
FROM workspace_column wc
JOIN workspace_table wt
  ON wt.id = wc.workspace_table_id
LEFT JOIN model_column mc
  ON mc.model_table_id = wt.model_table_id
 AND mc.column_name = wc.column_name
WHERE wt.model_table_id IS NOT NULL
  AND (:workspace_id IS NULL OR wt.workspace_id = :workspace_id)
"""

_COLUMN_CONFLICT_SAMPLES_QUERY = """
/* qf_backfill:column_conflict_samples */
SELECT
  wc.id AS workspace_column_id,
  wc.workspace_table_id,
  wt.workspace_id,
  wt.model_table_id,
  wc.column_name,
  COUNT(*) AS match_count
FROM workspace_column wc
JOIN workspace_table wt
  ON wt.id = wc.workspace_table_id
JOIN model_column mc
  ON mc.model_table_id = wt.model_table_id
 AND LOWER(mc.column_name) = LOWER(wc.column_name)
WHERE wt.model_table_id IS NOT NULL
  AND (:workspace_id IS NULL OR wt.workspace_id = :workspace_id)
GROUP BY wc.id, wc.workspace_table_id, wt.workspace_id, wt.model_table_id, wc.column_name
HAVING COUNT(*) > 1
ORDER BY match_count DESC, wc.id ASC
LIMIT :sample_limit
"""

_COLUMN_MISMATCH_COUNT_QUERY = """
/* qf_backfill:column_mismatch_count */
SELECT
  COUNT(*) AS mismatch_count
FROM workspace_column wc
JOIN workspace_table wt
  ON wt.id = wc.workspace_table_id
JOIN model_column mc
  ON mc.model_table_id = wt.model_table_id
 AND mc.column_name = wc.column_name
WHERE wt.model_table_id IS NOT NULL
  AND (:workspace_id IS NULL OR wt.workspace_id = :workspace_id)
  AND (
    COALESCE(wc.data_type, '') <> COALESCE(mc.data_type, '') OR
    COALESCE(wc.description, '') <> COALESCE(mc.description, '') OR
    COALESCE(wc.is_active, 1) <> COALESCE(mc.is_active, 1) OR
    COALESCE(wc.origin, '') <> COALESCE(mc.origin, '') OR
    COALESCE(wc.is_missing_in_source, 0) <> COALESCE(mc.is_missing_in_source, 0) OR
    COALESCE(wc.semantic_type, '') <> COALESCE(mc.semantic_type, '') OR
    COALESCE(wc.semantic_entity, '') <> COALESCE(mc.semantic_entity, '') OR
    COALESCE(wc.semantic_sub_type, '') <> COALESCE(mc.semantic_sub_type, '') OR
    COALESCE(wc.semantic_source, '') <> COALESCE(mc.semantic_source, '') OR
    COALESCE(wc.semantic_confidence, -1) <> COALESCE(mc.semantic_confidence, -1) OR
    COALESCE(wc.semantic_concept_key, '') <> COALESCE(mc.semantic_concept_key, '') OR
    COALESCE(CAST(wc.sample_values_json AS CHAR), '') <> COALESCE(CAST(mc.sample_values_json AS CHAR), '') OR
    COALESCE(CAST(wc.sample_stats_json AS CHAR), '') <> COALESCE(CAST(mc.sample_stats_json AS CHAR), '') OR
    COALESCE(DATE_FORMAT(wc.sample_ran_at, '%Y-%m-%d %H:%i:%s'), '') <> COALESCE(DATE_FORMAT(mc.sample_ran_at, '%Y-%m-%d %H:%i:%s'), '') OR
    COALESCE(wc.sample_error, '') <> COALESCE(mc.sample_error, '')
  )
"""

_COLUMN_MISMATCH_SAMPLE_QUERY = """
/* qf_backfill:column_mismatch_samples */
SELECT
  wc.id AS workspace_column_id,
  wc.workspace_table_id,
  wt.workspace_id,
  wt.model_table_id,
  wc.column_name,
  wc.data_type AS workspace_data_type,
  mc.data_type AS model_data_type
FROM workspace_column wc
JOIN workspace_table wt
  ON wt.id = wc.workspace_table_id
JOIN model_column mc
  ON mc.model_table_id = wt.model_table_id
 AND mc.column_name = wc.column_name
WHERE wt.model_table_id IS NOT NULL
  AND (:workspace_id IS NULL OR wt.workspace_id = :workspace_id)
  AND (
    COALESCE(wc.data_type, '') <> COALESCE(mc.data_type, '') OR
    COALESCE(wc.description, '') <> COALESCE(mc.description, '') OR
    COALESCE(wc.is_active, 1) <> COALESCE(mc.is_active, 1) OR
    COALESCE(wc.origin, '') <> COALESCE(mc.origin, '') OR
    COALESCE(wc.is_missing_in_source, 0) <> COALESCE(mc.is_missing_in_source, 0) OR
    COALESCE(wc.semantic_type, '') <> COALESCE(mc.semantic_type, '') OR
    COALESCE(wc.semantic_entity, '') <> COALESCE(mc.semantic_entity, '') OR
    COALESCE(wc.semantic_sub_type, '') <> COALESCE(mc.semantic_sub_type, '') OR
    COALESCE(wc.semantic_source, '') <> COALESCE(mc.semantic_source, '') OR
    COALESCE(wc.semantic_confidence, -1) <> COALESCE(mc.semantic_confidence, -1) OR
    COALESCE(wc.semantic_concept_key, '') <> COALESCE(mc.semantic_concept_key, '') OR
    COALESCE(CAST(wc.sample_values_json AS CHAR), '') <> COALESCE(CAST(mc.sample_values_json AS CHAR), '') OR
    COALESCE(CAST(wc.sample_stats_json AS CHAR), '') <> COALESCE(CAST(mc.sample_stats_json AS CHAR), '') OR
    COALESCE(DATE_FORMAT(wc.sample_ran_at, '%Y-%m-%d %H:%i:%s'), '') <> COALESCE(DATE_FORMAT(mc.sample_ran_at, '%Y-%m-%d %H:%i:%s'), '') OR
    COALESCE(wc.sample_error, '') <> COALESCE(mc.sample_error, '')
  )
ORDER BY wc.id
LIMIT :sample_limit
"""

_COLUMN_UPDATE_QUERY = """
/* qf_backfill:column_update */
UPDATE workspace_column wc
JOIN workspace_table wt
  ON wt.id = wc.workspace_table_id
JOIN model_column mc
  ON mc.model_table_id = wt.model_table_id
 AND mc.column_name = wc.column_name
SET
  wc.data_type = mc.data_type,
  wc.description = mc.description,
  wc.is_active = COALESCE(mc.is_active, 1),
  wc.origin = mc.origin,
  wc.is_missing_in_source = COALESCE(mc.is_missing_in_source, 0),
  wc.semantic_type = mc.semantic_type,
  wc.semantic_entity = mc.semantic_entity,
  wc.semantic_sub_type = mc.semantic_sub_type,
  wc.semantic_source = mc.semantic_source,
  wc.semantic_confidence = mc.semantic_confidence,
  wc.semantic_concept_key = mc.semantic_concept_key,
  wc.semantic_concept_id = mc.semantic_concept_id,
  wc.semantic_assigned_at = mc.semantic_assigned_at,
  wc.semantic_reasons_json = mc.semantic_reasons_json,
  wc.sample_values_json = mc.sample_values_json,
  wc.sample_stats_json = mc.sample_stats_json,
  wc.sample_ran_at = mc.sample_ran_at,
  wc.sample_error = mc.sample_error,
  wc.metadata_updated_at = CURRENT_TIMESTAMP
WHERE wt.model_table_id IS NOT NULL
  AND (:workspace_id IS NULL OR wt.workspace_id = :workspace_id)
  AND (
    COALESCE(wc.data_type, '') <> COALESCE(mc.data_type, '') OR
    COALESCE(wc.description, '') <> COALESCE(mc.description, '') OR
    COALESCE(wc.is_active, 1) <> COALESCE(mc.is_active, 1) OR
    COALESCE(wc.origin, '') <> COALESCE(mc.origin, '') OR
    COALESCE(wc.is_missing_in_source, 0) <> COALESCE(mc.is_missing_in_source, 0) OR
    COALESCE(wc.semantic_type, '') <> COALESCE(mc.semantic_type, '') OR
    COALESCE(wc.semantic_entity, '') <> COALESCE(mc.semantic_entity, '') OR
    COALESCE(wc.semantic_sub_type, '') <> COALESCE(mc.semantic_sub_type, '') OR
    COALESCE(wc.semantic_source, '') <> COALESCE(mc.semantic_source, '') OR
    COALESCE(wc.semantic_confidence, -1) <> COALESCE(mc.semantic_confidence, -1) OR
    COALESCE(wc.semantic_concept_key, '') <> COALESCE(mc.semantic_concept_key, '') OR
    COALESCE(CAST(wc.sample_values_json AS CHAR), '') <> COALESCE(CAST(mc.sample_values_json AS CHAR), '') OR
    COALESCE(CAST(wc.sample_stats_json AS CHAR), '') <> COALESCE(CAST(mc.sample_stats_json AS CHAR), '') OR
    COALESCE(DATE_FORMAT(wc.sample_ran_at, '%Y-%m-%d %H:%i:%s'), '') <> COALESCE(DATE_FORMAT(mc.sample_ran_at, '%Y-%m-%d %H:%i:%s'), '') OR
    COALESCE(wc.sample_error, '') <> COALESCE(mc.sample_error, '')
  )
"""


class WorkspaceMetadataBackfillService:
    def __init__(self, *, sql: Optional[ForgeQueryPort] = None) -> None:
        self._sql = sql or ForgeMetaSQL()

    def run(
        self,
        *,
        workspace_id: Optional[str] = None,
        dry_run: bool = True,
        sample_limit: int = 25,
    ) -> Dict[str, Any]:
        ws = str(workspace_id or "").strip() or None
        limit = max(1, min(int(sample_limit or 25), 200))
        params = {"workspace_id": ws, "sample_limit": limit}

        started = time.perf_counter()
        started_at = _utcnow_naive().isoformat(sep=" ", timespec="seconds")

        try:
            t_tables_0 = time.perf_counter()
            table_scope = self._first_row(_TABLE_SCOPE_COUNTS_QUERY, params)
            table_mismatch_count = self._scalar_count(_TABLE_MISMATCH_COUNT_QUERY, params, "mismatch_count")
            table_mismatch_samples = self._rows(_TABLE_MISMATCH_SAMPLE_QUERY, params)

            table_updated_rows = 0
            if not dry_run and table_mismatch_count > 0:
                table_updated_rows = int(self._sql.execute_write(_TABLE_UPDATE_QUERY, {"workspace_id": ws}) or 0)

            t_columns_0 = time.perf_counter()
            column_scope = self._first_row(_COLUMN_SCOPE_COUNTS_QUERY, params)
            column_conflicts = self._rows(_COLUMN_CONFLICT_SAMPLES_QUERY, params)
            column_mismatch_count = self._scalar_count(_COLUMN_MISMATCH_COUNT_QUERY, params, "mismatch_count")
            column_mismatch_samples = self._rows(_COLUMN_MISMATCH_SAMPLE_QUERY, params)

            column_updated_rows = 0
            if not dry_run and column_mismatch_count > 0:
                column_updated_rows = int(self._sql.execute_write(_COLUMN_UPDATE_QUERY, {"workspace_id": ws}) or 0)

            completed_at = _utcnow_naive().isoformat(sep=" ", timespec="seconds")
            total_ms = int((time.perf_counter() - started) * 1000)

            return {
                "workspace_id": ws,
                "dry_run": bool(dry_run),
                "started_at": started_at,
                "completed_at": completed_at,
                "tables": {
                    "workspace_table_rows": int(table_scope.get("workspace_table_rows") or 0),
                    "matched_model_table_rows": int(table_scope.get("matched_model_table_rows") or 0),
                    "missing_model_table_rows": int(table_scope.get("missing_model_table_rows") or 0),
                    "mismatch_count_before": int(table_mismatch_count),
                    "mismatch_samples": table_mismatch_samples,
                    "would_update_rows": int(table_mismatch_count),
                    "updated_rows": int(table_updated_rows),
                },
                "columns": {
                    "workspace_column_rows": int(column_scope.get("workspace_column_rows") or 0),
                    "matched_model_column_rows": int(column_scope.get("matched_model_column_rows") or 0),
                    "missing_model_column_rows": int(column_scope.get("missing_model_column_rows") or 0),
                    "mismatch_count_before": int(column_mismatch_count),
                    "mismatch_samples": column_mismatch_samples,
                    "would_update_rows": int(column_mismatch_count),
                    "updated_rows": int(column_updated_rows),
                },
                "conflicts": {
                    "case_insensitive_column_match_conflicts": column_conflicts,
                    "count": len(column_conflicts),
                },
                "timings_ms": {
                    "tables_stage": int((t_columns_0 - t_tables_0) * 1000),
                    "columns_stage": int((time.perf_counter() - t_columns_0) * 1000),
                    "total": total_ms,
                },
            }
        except ForgeError:
            raise
        except Exception as exc:
            raise ForgeError(
                "workspace metadata backfill failed",
                status_code=500,
                details={"workspace_id": ws, "dry_run": bool(dry_run), "error": str(exc)},
            ) from exc

    def _rows(self, query: str, params: Mapping[str, Any]) -> List[Dict[str, Any]]:
        return [dict(row) for row in self._sql.execute_query_mappings(query, dict(params))]

    def _first_row(self, query: str, params: Mapping[str, Any]) -> Dict[str, Any]:
        rows = self._rows(query, params)
        return dict(rows[0]) if rows else {}

    def _scalar_count(self, query: str, params: Mapping[str, Any], key: str) -> int:
        row = self._first_row(query, params)
        return int(row.get(key) or 0)


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


__all__ = ["WorkspaceMetadataBackfillService"]
