from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.ports.sql_executor import ForgeExecResult, ForgeQueryPort


class CatalogPromotionAuditRepository:
    def __init__(self, *, sql: Optional[ForgeQueryPort] = None) -> None:
        self._sql = sql or ForgeMetaSQL()

    def create_audit(self, *, payload: Dict[str, Any]) -> ForgeExecResult:
        return self._sql.execute_insert(
            """
            INSERT INTO catalog_promotion_audit (
              source_type,
              source_id,
              target_table,
              target_record_key,
              promotion_action,
              promotion_status,
              promoted_by,
              promoted_at,
              retry_count,
              last_retry_at,
              notes,
              error_message
            ) VALUES (
              :source_type,
              :source_id,
              :target_table,
              :target_record_key,
              :promotion_action,
              :promotion_status,
              :promoted_by,
              :promoted_at,
              :retry_count,
              :last_retry_at,
              :notes,
              :error_message
            )
            """,
            dict(payload),
        )

    def update_failure(
        self,
        *,
        audit_id: int,
        retry_count: int,
        last_retry_at: Any,
        error_message: Optional[str],
        promotion_status: str = "failed",
    ) -> int:
        return int(
            self._sql.execute_write(
                """
                UPDATE catalog_promotion_audit
                SET retry_count = :retry_count,
                    last_retry_at = :last_retry_at,
                    error_message = :error_message,
                    promotion_status = :promotion_status
                WHERE id = :id
                """,
                {
                    "id": int(audit_id),
                    "retry_count": int(retry_count),
                    "last_retry_at": last_retry_at,
                    "error_message": error_message,
                    "promotion_status": str(promotion_status or "").strip(),
                },
            )
            or 0
        )

    def get_latest_by_source(
        self,
        *,
        source_type: str,
        source_id: int,
        promotion_action: Optional[str] = None,
        target_table: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        filters = [
            "source_type = :source_type",
            "source_id = :source_id",
        ]
        params: Dict[str, Any] = {
            "source_type": str(source_type or "").strip(),
            "source_id": int(source_id),
        }
        if str(promotion_action or "").strip():
            filters.append("promotion_action = :promotion_action")
            params["promotion_action"] = str(promotion_action).strip()
        if str(target_table or "").strip():
            filters.append("target_table = :target_table")
            params["target_table"] = str(target_table).strip()

        rows = self._sql.execute_query_mappings(
            f"""
            SELECT *
            FROM catalog_promotion_audit
            WHERE {' AND '.join(filters)}
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """,
            params,
        )
        return dict(rows[0]) if rows else None

    def list_audits(
        self,
        *,
        source_type: Optional[str] = None,
        promotion_status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Dict[str, Any]:
        filters = []
        params: Dict[str, Any] = {}
        if str(source_type or "").strip():
            params["source_type"] = str(source_type).strip()
            filters.append("source_type = :source_type")
        if str(promotion_status or "").strip():
            params["promotion_status"] = str(promotion_status).strip()
            filters.append("promotion_status = :promotion_status")
        where_sql = f"WHERE {' AND '.join(filters)}" if filters else ""
        params["limit"] = max(1, min(200, int(limit or 50)))
        params["offset"] = max(0, int(offset or 0))

        rows = self._sql.execute_query_mappings(
            f"""
            SELECT *
            FROM catalog_promotion_audit
            {where_sql}
            ORDER BY created_at DESC, id DESC
            LIMIT :limit OFFSET :offset
            """,
            params,
        )
        total_rows = self._sql.execute_query_mappings(
            f"""
            SELECT COUNT(*) AS total
            FROM catalog_promotion_audit
            {where_sql}
            """,
            {k: v for k, v in params.items() if k not in {"limit", "offset"}},
        )
        total = int((total_rows[0] or {}).get("total") or 0) if total_rows else 0
        return {
            "rows": [dict(row) for row in rows],
            "total": total,
            "limit": int(params["limit"]),
            "offset": int(params["offset"]),
        }


__all__ = ["CatalogPromotionAuditRepository"]
