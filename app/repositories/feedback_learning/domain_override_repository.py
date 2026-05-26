from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.ports.sql_executor import ForgeExecResult, ForgeQueryPort

from app.repositories.feedback_learning._shared import parse_json_object, serialize_json_object


class DomainOverrideRepository:
    def __init__(self, *, sql: Optional[ForgeQueryPort] = None) -> None:
        self._sql = sql or ForgeMetaSQL()

    def get_by_id(self, *, override_id: int) -> Optional[Dict[str, Any]]:
        rows = self._sql.execute_query_mappings(
            """
            SELECT *
            FROM domain_override
            WHERE id = :id
            LIMIT 1
            """,
            {"id": int(override_id)},
        )
        return _normalize_override_row(rows[0]) if rows else None

    def insert_override(self, *, payload: Dict[str, Any]) -> ForgeExecResult:
        params = dict(payload)
        params["override_value_json"] = serialize_json_object(payload.get("override_value_json") or payload.get("override_value"))
        return self._sql.execute_insert(
            """
            INSERT INTO domain_override (
              workspace_id,
              domain_key,
              override_type,
              override_key,
              override_value_json,
              source_candidate_id,
              status,
              approved_by
            ) VALUES (
              :workspace_id,
              :domain_key,
              :override_type,
              :override_key,
              :override_value_json,
              :source_candidate_id,
              :status,
              :approved_by
            )
            """,
            params,
        )

    def list_overrides(
        self,
        *,
        workspace_id: Optional[str] = None,
        status: Optional[str] = None,
        domain_key: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        filters = []
        params: Dict[str, Any] = {}
        for key, value in (("workspace_id", workspace_id), ("status", status), ("domain_key", domain_key)):
            token = str(value or "").strip()
            if token == "":
                continue
            filters.append(f"{key} = :{key}")
            params[key] = token
        where_sql = f"WHERE {' AND '.join(filters)}" if filters else ""
        rows = self._sql.execute_query_mappings(
            f"""
            SELECT *
            FROM domain_override
            {where_sql}
            ORDER BY created_at DESC, id DESC
            """,
            params,
        )
        return [_normalize_override_row(row) for row in rows]

    def find_active_override(
        self,
        *,
        workspace_id: Optional[str],
        domain_key: str,
        override_type: str,
        override_key: str,
    ) -> Optional[Dict[str, Any]]:
        workspace_sql = "workspace_id IS NULL" if workspace_id is None else "workspace_id = :workspace_id"
        params: Dict[str, Any] = {
            "domain_key": str(domain_key or "").strip(),
            "override_type": str(override_type or "").strip(),
            "override_key": str(override_key or "").strip(),
        }
        if workspace_id is not None:
            params["workspace_id"] = str(workspace_id).strip()
        rows = self._sql.execute_query_mappings(
            f"""
            SELECT *
            FROM domain_override
            WHERE {workspace_sql}
              AND domain_key = :domain_key
              AND override_type = :override_type
              AND override_key = :override_key
              AND status = 'active'
            LIMIT 1
            """,
            params,
        )
        return _normalize_override_row(rows[0]) if rows else None

    def deactivate(self, *, override_id: int) -> int:
        return int(
            self._sql.execute_write(
                """
                UPDATE domain_override
                SET status = 'inactive',
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = :id
                """,
                {"id": int(override_id)},
            )
            or 0
        )


def _normalize_override_row(raw: Dict[str, Any]) -> Dict[str, Any]:
    row = dict(raw)
    row["override_value_json"] = parse_json_object(row.get("override_value_json"))
    return row


__all__ = ["DomainOverrideRepository"]
