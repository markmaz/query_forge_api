from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.ports.sql_executor import ForgeExecResult, ForgeQueryPort


class OAuthAuthorizationCodeRepository:
    def __init__(self, *, sql: Optional[ForgeQueryPort] = None) -> None:
        self._sql = sql or ForgeMetaSQL()

    def create_code(self, *, payload: Dict[str, Any]) -> ForgeExecResult:
        return self._sql.execute_insert(
            """
            INSERT INTO oauth_authorization_codes (
              code_hash,
              client_id,
              principal_type,
              principal_id,
              redirect_uri,
              resource,
              scope,
              code_challenge,
              code_challenge_method,
              nonce,
              state_hash,
              expires_at
            ) VALUES (
              :code_hash,
              :client_id,
              :principal_type,
              :principal_id,
              :redirect_uri,
              :resource,
              :scope,
              :code_challenge,
              :code_challenge_method,
              :nonce,
              :state_hash,
              :expires_at
            )
            """,
            dict(payload),
        )

    def consume_code(self, *, code_hash: str, now: datetime) -> Optional[Dict[str, Any]]:
        params = {"code_hash": str(code_hash or "").strip(), "now": now}
        rows = self._sql.execute_query_mappings(
            """
            SELECT *
            FROM oauth_authorization_codes
            WHERE code_hash = :code_hash
              AND consumed_at IS NULL
              AND expires_at > :now
            LIMIT 1
            """,
            params,
        )
        if not rows:
            return None
        updated = self._sql.execute_write(
            """
            UPDATE oauth_authorization_codes
            SET consumed_at = :now
            WHERE code_hash = :code_hash
              AND consumed_at IS NULL
              AND expires_at > :now
            """,
            params,
        )
        if int(updated or 0) != 1:
            return None
        return dict(rows[0])


__all__ = ["OAuthAuthorizationCodeRepository"]
