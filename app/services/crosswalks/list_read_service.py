# app/services/lists/list_read_service.py
from __future__ import annotations

import logging
from typing import List, Optional

import pyarrow as pa

from app.exceptions.service_error import ServiceError
from app.models.crosswalk import (
    CrosswalkDetails,
    CrosswalkListIndex,
    CrosswalkMeta,
    SectionKey,
)
from app.ports.sql_executor import SQLExecutor
from app.services.crosswalks.list_schema import DATA_COLUMNS_BY_TYPE, TABLE_BY_TYPE

logger = logging.getLogger(__name__)

class ListReadService:
    def __init__(self, *, mysql: SQLExecutor, dbx: SQLExecutor, workspace_id: str):
        self._mysql = mysql
        self._dbx = dbx
        self._workspace_id = workspace_id

    def get_index(self, *, include_expired: bool = False) -> CrosswalkListIndex:
        return CrosswalkListIndex(
            regions=self._fetch_index_for_type("regions", include_expired=include_expired),
            npiCategories=self._fetch_index_for_type("npiCategories", include_expired=include_expired),
            serviceLines=self._fetch_index_for_type("serviceLines", include_expired=include_expired),
        )

    def get_preview_by_id(
        self,
        *,
        list_type: SectionKey,
        list_id: str,
        limit: int = 100,
        offset: int = 0,
        include_expired: bool = False,
    ) -> CrosswalkDetails:
        list_name, owner = self._resolve_meta_by_id(
            list_type=list_type,
            list_id=list_id,
            include_expired=include_expired,
        )

        table = TABLE_BY_TYPE[list_type]
        cols = DATA_COLUMNS_BY_TYPE[list_type]
        col_names = [c.name for c in cols]

        cols_sql = ", ".join(f"`{c}`" for c in col_names)
        table_sql = ".".join(f"`{p}`" for p in table.split("."))

        order_col = col_names[0]  # simple stable default
        sql_rows = f"""
                SELECT {cols_sql}
                FROM {table_sql}
                WHERE `list_id` = :list_id
                ORDER BY `{order_col}` ASC
                LIMIT :limit
                OFFSET :offset
                """.strip()

        sql_count = f"""
                SELECT COUNT(*) AS total_rows
                FROM {table_sql}
                WHERE `list_id` = :list_id
                """.strip()

        params = {
            "list_id": list_id,
            "limit": int(limit),
            "offset": int(offset),
        }

        rows_resp = self._dbx.submit_statement(sql_rows, parameters=params, result_format="ARROW_STREAM")
        rows = _rows_from_resp(rows_resp)

        count_resp = self._dbx.submit_statement(
            sql_count,
            parameters={"list_id": list_id},
            result_format="ARROW_STREAM",
        )
        total_rows = 0
        count_rows = _rows_from_resp(count_resp)
        if count_rows:
            total_rows = int((count_rows[0] or {}).get("total_rows") or 0)

        return CrosswalkDetails(
            list_id=list_id,
            list_name=list_name,
            list_type=list_type,
            columns=cols,
            rows=rows,
            total_rows=total_rows,
            limit=int(limit),
            offset=int(offset),
        )
    
    def delete_list(self, *, list_type: SectionKey, list_id: str) -> None:
        if list_type not in TABLE_BY_TYPE:
            raise ServiceError("Invalid crosswalk_type", status_code=400)

        table = TABLE_BY_TYPE[list_type]
        table_sql = ".".join(f"`{p}`" for p in table.split("."))

        # Delete all rows for that list
        sql_delete = f"""
        DELETE FROM {table_sql}
        WHERE `list_id` = :list_id
        """.strip()

        resp = self._dbx.submit_statement(
            sql_delete,
            parameters={
                "list_id": list_id,
            },
            result_format="JSON_ARRAY",
        )

        if (resp.get("status") or {}).get("state") != "SUCCEEDED":
            logger.error("Delete failed list_id=%s resp=%s", list_id, resp)
            raise ServiceError("Delete failed", status_code=500)

        self._mysql.execute_write(
            """
            DELETE FROM crosswalk_list_meta
            WHERE workspace_id = :ws
              AND list_type = :type
              AND list_id = :list_id
            """.strip(),
            {"ws": self._workspace_id, "type": list_type, "list_id": list_id},
        )

    # ---------------- internals ----------------

    def _fetch_index_for_type(self, list_type: SectionKey, *, include_expired: bool) -> List[CrosswalkMeta]:
        sql = """
                SELECT
                list_id AS list_id,
                list_name AS list_name,
                user_name AS owner,
                user_id AS user_id,
                is_shared AS is_shared,
                created_at AS created_at,
                updated_at AS updated_at
                FROM crosswalk_list_meta
                WHERE workspace_id = :ws
                  AND list_type = :type
                ORDER BY updated_at DESC, list_name ASC
                """.strip()

        rows = self._mysql.execute_query_mappings(
            sql,
            {
                "ws": self._workspace_id,
                "type": list_type,
            },
        )

        out: List[CrosswalkMeta] = []
        for r in rows:
            list_id = (r.get("list_id") or "").strip()
            list_name = (r.get("list_name") or "").strip()
            owner = (r.get("owner") or "").strip()
            if not list_id or not list_name or not owner:
                continue

            out.append(
                CrosswalkMeta(
                    list_id=list_id,
                    list_name=list_name,
                    owner=owner,
                    user_id=(r.get("user_id") or "").strip() or None,
                    is_shared=_to_bool(r.get("is_shared")),
                    created_at=r["created_at"],
                    updated_at=r["updated_at"],
                    row_count=int(r.get("row_count") or 0),
                    expires_at=None,
                )
            )

        return out

    def _resolve_meta_by_id(self, *, list_type: SectionKey, list_id: str, include_expired: bool) -> tuple[str, str]:
        sql = """
        SELECT list_name AS list_name, user_name AS owner
        FROM crosswalk_list_meta
        WHERE workspace_id = :ws
          AND list_type = :type
          AND list_id = :list_id
        LIMIT 1
        """.strip()

        rows = self._mysql.execute_query_mappings(
            sql,
            {
                "ws": self._workspace_id,
                "type": list_type,
                "list_id": list_id,
            },
        )
        if not rows:
            raise ValueError("List not found")

        row = rows[0]
        list_name = (row.get("list_name") or "").strip()
        owner = (row.get("owner") or "").strip()
        if not list_name or not owner:
            raise ValueError("List not found")

        return list_name, owner


def _rows_from_resp(resp: dict) -> List[dict]:
    if "table" in resp:
        table: Optional[pa.Table] = resp.get("table")
        if table is not None:
            return table.to_pylist() or []
    rows = resp.get("rows")
    return rows if isinstance(rows, list) else []


def _to_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return int(value) != 0
    if value is None:
        return False
    return str(value).strip().lower() in ("1", "true", "yes", "y", "on")
