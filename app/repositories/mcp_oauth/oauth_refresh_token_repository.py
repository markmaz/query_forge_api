from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.ports.sql_executor import ForgeExecResult, ForgeQueryPort


class OAuthRefreshTokenRepository:
    def __init__(self, *, sql: Optional[ForgeQueryPort] = None) -> None:
        self._sql = sql or ForgeMetaSQL()

    def create_refresh_token(self, *, payload: Dict[str, Any]) -> ForgeExecResult:
        return self._sql.execute_insert(
            """
            INSERT INTO oauth_refresh_tokens (
              token_hash,
              client_id,
              principal_type,
              principal_id,
              resource,
              scope,
              expires_at
            ) VALUES (
              :token_hash,
              :client_id,
              :principal_type,
              :principal_id,
              :resource,
              :scope,
              :expires_at
            )
            """,
            dict(payload),
        )

    def get_active_refresh_token(self, *, token_hash: str, now: datetime) -> Optional[Dict[str, Any]]:
        rows = self._sql.execute_query_mappings(
            """
            SELECT *
            FROM oauth_refresh_tokens
            WHERE token_hash = :token_hash
              AND rotated_at IS NULL
              AND revoked_at IS NULL
              AND expires_at > :now
            LIMIT 1
            """,
            {
                "token_hash": str(token_hash or "").strip(),
                "now": now,
            },
        )
        if not rows:
            return None
        return dict(rows[0])

    def rotate_refresh_token(self, *, token_hash: str, replacement_hash: str, now: datetime) -> bool:
        updated = self._sql.execute_write(
            """
            UPDATE oauth_refresh_tokens
            SET rotated_at = :now,
                revoked_at = :now,
                replaced_by_hash = :replacement_hash
            WHERE token_hash = :token_hash
              AND rotated_at IS NULL
              AND revoked_at IS NULL
              AND expires_at > :now
            """,
            {
                "token_hash": str(token_hash or "").strip(),
                "replacement_hash": str(replacement_hash or "").strip(),
                "now": now,
            },
        )
        return int(updated or 0) == 1

    def revoke_refresh_token(self, *, token_hash: str, now: datetime) -> bool:
        updated = self._sql.execute_write(
            """
            UPDATE oauth_refresh_tokens
            SET revoked_at = :now
            WHERE token_hash = :token_hash
              AND revoked_at IS NULL
            """,
            {
                "token_hash": str(token_hash or "").strip(),
                "now": now,
            },
        )
        return int(updated or 0) > 0


__all__ = ["OAuthRefreshTokenRepository"]
