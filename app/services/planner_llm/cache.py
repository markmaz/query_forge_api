from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.ports.sql_executor import ForgeQueryPort

logger = logging.getLogger(__name__)


class PlannerLLMCache:
    def __init__(self, *, sql: Optional[ForgeQueryPort] = None, ttl_days: int = 7) -> None:
        self._sql = sql or ForgeMetaSQL()
        self._ttl_days = max(1, int(ttl_days))

    @staticmethod
    def build_cache_key(
        *,
        workspace_id: str,
        vertical: str,
        normalized_prompt: str,
        constraints: Dict[str, Any],
        registry_version: str,
    ) -> str:
        payload = {
            "workspace_id": str(workspace_id),
            "vertical": str(vertical),
            "normalized_prompt": str(normalized_prompt),
            "constraints": constraints,
            "registry_version": str(registry_version),
        }
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def get_registry_version(self, *, vertical: str) -> str:
        rows = self._sql.execute_query_mappings(
            """
            SELECT
              COALESCE(MAX(UNIX_TIMESTAMP(updated_at)), 0) AS max_ts,
              COUNT(*) AS concept_count
            FROM semantic_concept
            WHERE vertical_norm IN (:vertical, 'generic')
              AND `status` = 'active'
            """,
            {"vertical": str(vertical or "generic").strip().lower() or "generic"},
        )
        row = rows[0] if rows else {}
        max_ts = int(row.get("max_ts") or 0)
        concept_count = int(row.get("concept_count") or 0)
        return f"v{max_ts}:{concept_count}"

    def get(self, *, cache_key: str, registry_version: str) -> Optional[Dict[str, Any]]:
        try:
            rows = self._sql.execute_query_mappings(
                """
                SELECT
                  cache_key,
                  plan_json,
                  sql_json,
                  validation_json,
                  candidates_json
                FROM planner_cache
                WHERE cache_key = :cache_key
                  AND registry_version = :registry_version
                  AND expires_at > UTC_TIMESTAMP()
                LIMIT 1
                """,
                {"cache_key": cache_key, "registry_version": registry_version},
            )
        except Exception as exc:
            if _is_missing_planner_cache_table(exc):
                logger.warning("planner_llm cache disabled: planner_cache table missing")
                return None
            raise
        row = rows[0] if rows else None
        if not row:
            return None
        return {
            "plan_json": _loads_json(row.get("plan_json")) or {},
            "sql_json": _loads_json(row.get("sql_json")) or {},
            "validation": _loads_json(row.get("validation_json")) or {},
            "candidates": _loads_json(row.get("candidates_json")) or {"domains": [], "concepts": [], "columns": []},
        }

    def set(
        self,
        *,
        cache_key: str,
        workspace_id: str,
        vertical: str,
        normalized_prompt: str,
        constraints: Dict[str, Any],
        registry_version: str,
        plan_json: Dict[str, Any],
        sql_json: Dict[str, Any],
        validation: Dict[str, Any],
        candidates: Dict[str, Any],
    ) -> None:
        expires_at = datetime.now(timezone.utc) + timedelta(days=self._ttl_days)
        try:
            self._sql.execute_write(
                """
                INSERT INTO planner_cache (
                  cache_key,
                  workspace_id,
                  vertical,
                  normalized_prompt,
                  constraints_json,
                  registry_version,
                  plan_json,
                  sql_json,
                  validation_json,
                  candidates_json,
                  expires_at,
                  created_at,
                  updated_at
                )
                VALUES (
                  :cache_key,
                  :workspace_id,
                  :vertical,
                  :normalized_prompt,
                  :constraints_json,
                  :registry_version,
                  :plan_json,
                  :sql_json,
                  :validation_json,
                  :candidates_json,
                  :expires_at,
                  UTC_TIMESTAMP(),
                  UTC_TIMESTAMP()
                )
                ON DUPLICATE KEY UPDATE
                  constraints_json = VALUES(constraints_json),
                  registry_version = VALUES(registry_version),
                  plan_json = VALUES(plan_json),
                  sql_json = VALUES(sql_json),
                  validation_json = VALUES(validation_json),
                  candidates_json = VALUES(candidates_json),
                  expires_at = VALUES(expires_at),
                  updated_at = UTC_TIMESTAMP()
                """,
                {
                    "cache_key": cache_key,
                    "workspace_id": str(workspace_id),
                    "vertical": str(vertical),
                    "normalized_prompt": str(normalized_prompt),
                    "constraints_json": json.dumps(constraints, ensure_ascii=True),
                    "registry_version": str(registry_version),
                    "plan_json": json.dumps(plan_json, ensure_ascii=True),
                    "sql_json": json.dumps(sql_json, ensure_ascii=True),
                    "validation_json": json.dumps(validation, ensure_ascii=True),
                    "candidates_json": json.dumps(candidates, ensure_ascii=True),
                    "expires_at": expires_at.strftime("%Y-%m-%d %H:%M:%S"),
                },
            )
        except Exception as exc:
            if _is_missing_planner_cache_table(exc):
                logger.warning("planner_llm cache write skipped: planner_cache table missing")
                return
            raise


def _loads_json(value: Any) -> Optional[Dict[str, Any]]:
    if value is None:
        return None
    text = str(value or "").strip()
    if text == "":
        return None
    try:
        parsed = json.loads(text)
    except Exception:
        return None
    return parsed if isinstance(parsed, dict) else None


def _is_missing_planner_cache_table(exc: Exception) -> bool:
    msg = str(exc).lower()
    return ("planner_cache" in msg) and ("doesn't exist" in msg or "does not exist" in msg or "1146" in msg)


__all__ = ["PlannerLLMCache"]
