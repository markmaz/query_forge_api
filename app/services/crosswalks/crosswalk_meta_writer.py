from __future__ import annotations

from typing import Optional
from uuid import uuid4

from app.exceptions.service_error import ServiceError
from app.ports.sql_executor import SQLExecutor


class CrosswalkMetaWriter:
    def __init__(self, mysql: SQLExecutor) -> None:
        self._sql = mysql
        self._checked = False

    def upsert_meta(
        self,
        *,
        workspace_id: str,
        list_type: str,
        list_id: str,
        list_name: str,
        user_id: Optional[str],
        user_name: Optional[str],
        is_shared: bool,
    ) -> None:
        self._assert_table_exists_once()
        row_id = str(uuid4())

        sql = """
        INSERT INTO crosswalk_list_meta
          (id, workspace_id, list_type, list_id, list_name, user_id, user_name, is_shared)
        VALUES
          (:id, :workspace_id, :list_type, :list_id, :list_name, :user_id, :user_name, :is_shared)
        ON DUPLICATE KEY UPDATE
          list_name = VALUES(list_name),
          user_id = VALUES(user_id),
          user_name = VALUES(user_name),
          is_shared = VALUES(is_shared),
          updated_at = CURRENT_TIMESTAMP
        """.strip()

        self._sql.execute_write(
            sql,
            {
                "id": row_id,
                "workspace_id": workspace_id,
                "list_type": list_type,
                "list_id": list_id,
                "list_name": list_name,
                "user_id": user_id,
                "user_name": user_name,
                "is_shared": 1 if is_shared else 0,
            },
        )

    def set_shared(
        self,
        *,
        workspace_id: str,
        list_type: str,
        list_id: str,
        is_shared: bool,
    ) -> None:
        self._assert_table_exists_once()
        row_id = str(uuid4())

        sql = """
        INSERT INTO crosswalk_list_meta
          (id, workspace_id, list_type, list_id, list_name, is_shared)
        VALUES
          (:id, :workspace_id, :list_type, :list_id, :list_name, :is_shared)
        ON DUPLICATE KEY UPDATE
          is_shared = VALUES(is_shared),
          updated_at = CURRENT_TIMESTAMP
        """.strip()

        self._sql.execute_write(
            sql,
            {
                "id": row_id,
                "workspace_id": workspace_id,
                "list_type": list_type,
                "list_id": list_id,
                "list_name": "",
                "is_shared": 1 if is_shared else 0,
            },
        )

    def delete_meta(self, *, workspace_id: str, list_type: str, list_id: str) -> None:
        self._assert_table_exists_once()
        self._sql.execute_write(
            """
            DELETE FROM crosswalk_list_meta
            WHERE workspace_id = :workspace_id
              AND list_type = :list_type
              AND list_id = :list_id
            """.strip(),
            {
                "workspace_id": workspace_id,
                "list_type": list_type,
                "list_id": list_id,
            },
        )

    def _assert_table_exists_once(self) -> None:
        if self._checked:
            return
        try:
            self._sql.execute_query_mappings("SELECT 1 FROM crosswalk_list_meta LIMIT 1")
        except Exception as exc:  # narrow mysql errors without importing driver
            raise ServiceError("crosswalk_list_meta missing; run migrations", status_code=500) from exc
        self._checked = True
