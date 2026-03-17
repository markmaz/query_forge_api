from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import text

from app.adapters.mysql_sql_executor import engine

logger = logging.getLogger(__name__)


def _parse_json_field(value: Any) -> Any:
    """MySQL JSON columns arrive as strings; parse them, return None on failure."""
    if value is None:
        return None
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except Exception:
        return None


class DictionaryService:
    # ------------------------------------------------------------------
    # Tables
    # ------------------------------------------------------------------

    def list_tables(
        self,
        *,
        workspace_id: str,
        q: str | None,
        limit: int,
        offset: int,
    ) -> dict:
        params: dict = {"ws": workspace_id, "limit": limit, "offset": offset}
        q_clause = ""
        if q:
            q_clause = "AND wt.table_name LIKE :q"
            params["q"] = f"%{q}%"

        sql = f"""
        SELECT
            wt.id,
            wt.table_name,
            wt.full_name,
            wt.schema_name,
            wt.catalog_name,
            wt.description
        FROM workspace_table wt
        WHERE wt.workspace_id = :ws
          {q_clause}
        ORDER BY wt.table_name ASC
        LIMIT :limit OFFSET :offset
        """

        count_sql = f"""
        SELECT COUNT(*) AS total
        FROM workspace_table wt
        WHERE wt.workspace_id = :ws
          {q_clause}
        """

        with engine.connect() as conn:
            rows = [dict(r) for r in conn.execute(text(sql), params).mappings().all()]
            count_params = {k: v for k, v in params.items() if k != "limit" and k != "offset"}
            total = conn.execute(text(count_sql), count_params).fetchone()[0]

        return {"rows": rows, "total": int(total), "limit": limit, "offset": offset}

    # ------------------------------------------------------------------
    # Columns
    # ------------------------------------------------------------------

    _COLUMN_SELECT = """
        SELECT
            wc.id,
            wc.workspace_table_id,
            wc.column_name,
            wc.data_type,
            wc.ordinal_position,
            wc.description,
            wc.is_active,
            wc.semantic_type,
            wc.semantic_entity,
            wc.semantic_sub_type,
            wc.semantic_confidence,
            wc.sample_values_json,
            wc.sample_stats_json,
            wc.sample_ran_at,
            wc.sample_error,
            wt.table_name,
            wt.full_name
        FROM workspace_column wc
        JOIN workspace_table wt ON wt.id = wc.workspace_table_id
    """

    def _normalize_column_row(self, row: dict) -> dict:
        r = dict(row)
        r["is_active"] = bool(r.get("is_active"))
        r["sample_values_json"] = _parse_json_field(r.get("sample_values_json"))
        r["sample_stats_json"] = _parse_json_field(r.get("sample_stats_json"))
        return r

    def list_columns(
        self,
        *,
        workspace_id: str,
        workspace_table_id: int,
        q: str | None,
        active_only: bool,
    ) -> dict:
        from app.exceptions.forge_error import ForgeError

        params: dict = {"ws": workspace_id, "wtid": workspace_table_id}
        active_clause = "AND wc.is_active = 1" if active_only else ""
        q_clause = ""
        if q:
            q_clause = "AND wc.column_name LIKE :q"
            params["q"] = f"%{q}%"

        sql = f"""
        {self._COLUMN_SELECT}
        WHERE wt.workspace_id = :ws
          AND wc.workspace_table_id = :wtid
          {active_clause}
          {q_clause}
        ORDER BY wc.ordinal_position ASC, wc.column_name ASC
        """

        with engine.connect() as conn:
            rows = [dict(r) for r in conn.execute(text(sql), params).mappings().all()]

        if not rows:
            # Verify the table belongs to this workspace; 404 if not
            check_sql = """
            SELECT 1 FROM workspace_table
            WHERE id = :wtid AND workspace_id = :ws LIMIT 1
            """
            with engine.connect() as conn:
                found = conn.execute(
                    text(check_sql), {"wtid": workspace_table_id, "ws": workspace_id}
                ).fetchone()
            if not found:
                raise ForgeError("Workspace table not found", status_code=404)

        return {"rows": [self._normalize_column_row(r) for r in rows]}

    def search_columns(
        self,
        *,
        workspace_id: str,
        q: str,
        limit: int,
        active_only: bool,
    ) -> dict:
        params: dict = {"ws": workspace_id, "q": f"%{q}%", "limit": limit}
        active_clause = "AND wc.is_active = 1" if active_only else ""

        sql = f"""
        {self._COLUMN_SELECT}
        WHERE wt.workspace_id = :ws
          {active_clause}
          AND (wc.column_name LIKE :q OR wc.description LIKE :q OR wt.table_name LIKE :q)
        ORDER BY wt.table_name ASC, wc.column_name ASC
        LIMIT :limit
        """

        with engine.connect() as conn:
            rows = [dict(r) for r in conn.execute(text(sql), params).mappings().all()]

        return {"rows": [self._normalize_column_row(r) for r in rows]}

    # ------------------------------------------------------------------
    # Patch
    # ------------------------------------------------------------------

    _ALLOWED_PATCH_FIELDS = frozenset({
        "description",
        "data_type",
        "is_active",
        "semantic_type",
        "semantic_entity",
        "semantic_sub_type",
        "semantic_confidence",
    })

    def patch_column(self, *, workspace_id: str, column_id: int, patch: dict) -> dict:
        from app.exceptions.forge_error import ForgeError

        allowed = {k: v for k, v in patch.items() if k in self._ALLOWED_PATCH_FIELDS}
        if not allowed:
            raise ForgeError("No patchable fields provided", status_code=400)

        set_clauses = ", ".join(f"wc.{col} = :{col}" for col in allowed)
        params: dict = {"col_id": column_id, "ws": workspace_id, **allowed}

        update_sql = f"""
        UPDATE workspace_column wc
        JOIN workspace_table wt ON wt.id = wc.workspace_table_id
        SET {set_clauses}
        WHERE wc.id = :col_id
          AND wt.workspace_id = :ws
        """

        fetch_sql = f"""
        {self._COLUMN_SELECT}
        WHERE wc.id = :col_id AND wt.workspace_id = :ws
        LIMIT 1
        """

        with engine.connect() as conn:
            result = conn.execute(text(update_sql), params)
            if result.rowcount == 0:
                raise ForgeError("Column not found", status_code=404)
            conn.commit()

        with engine.connect() as conn:
            rows = [dict(r) for r in conn.execute(
                text(fetch_sql), {"col_id": column_id, "ws": workspace_id}
            ).mappings().all()]

        if not rows:
            raise ForgeError("Column not found", status_code=404)
        return {"row": self._normalize_column_row(rows[0])}

    # ------------------------------------------------------------------
    # Import
    # ------------------------------------------------------------------

    def import_columns(
        self,
        *,
        workspace_id: str,
        rows: list[dict],
        full_replace: bool,
    ) -> dict:
        update_sql = """
        UPDATE workspace_column wc
        JOIN workspace_table wt ON wt.id = wc.workspace_table_id
        SET wc.description = :description,
            wc.data_type = COALESCE(:data_type, wc.data_type)
        WHERE wt.workspace_id = :ws
          AND wt.table_name = :table_name
          AND wc.column_name = :column_name
        """

        clear_sql = """
        UPDATE workspace_column wc
        JOIN workspace_table wt ON wt.id = wc.workspace_table_id
        SET wc.description = NULL, wc.data_type = NULL
        WHERE wt.workspace_id = :ws
        """

        updated = 0
        unmatched: list[dict] = []

        with engine.connect() as conn:
            if full_replace:
                conn.execute(text(clear_sql), {"ws": workspace_id})

            for row in rows:
                params = {
                    "ws": workspace_id,
                    "table_name": str(row.get("table_name") or "").strip(),
                    "column_name": str(row.get("column_name") or "").strip(),
                    "description": row.get("description") or None,
                    "data_type": row.get("data_type") or None,
                }
                result = conn.execute(text(update_sql), params)
                if result.rowcount > 0:
                    updated += 1
                else:
                    unmatched.append({
                        "table_name": params["table_name"],
                        "column_name": params["column_name"],
                    })

            conn.commit()

        return {"updated": updated, "unmatched": unmatched}
