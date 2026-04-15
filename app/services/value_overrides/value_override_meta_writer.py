from __future__ import annotations

from typing import Optional
from uuid import uuid4

from app.exceptions.forge_error import ForgeError
from app.ports.sql_executor import ForgeQueryPort

TABLE_CHECK_FALLBACK_ERRORS = (OSError, RuntimeError, TypeError, ValueError)


class ValueOverrideMetaWriter:
    def __init__(self, mysql: ForgeQueryPort) -> None:
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
        sql = """
        UPDATE crosswalk_list_meta
        SET is_shared = :is_shared,
            updated_at = CURRENT_TIMESTAMP
        WHERE workspace_id = :workspace_id
          AND list_type = :list_type
          AND list_id = :list_id
        """.strip()

        updated = self._sql.execute_write(
            sql,
            {
                "workspace_id": workspace_id,
                "list_type": list_type,
                "list_id": list_id,
                "is_shared": 1 if is_shared else 0,
            },
        )
        if not updated:
            raise ForgeError("List not found", status_code=404)

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
        except TABLE_CHECK_FALLBACK_ERRORS as exc:  # narrow mysql errors without importing driver
            raise ForgeError("crosswalk_list_meta missing; run migrations", status_code=500) from exc
        self._checked = True
