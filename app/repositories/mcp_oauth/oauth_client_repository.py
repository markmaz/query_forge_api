from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, Optional

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.ports.sql_executor import ForgeExecResult, ForgeQueryPort


def _json_or_none(value: Any) -> Optional[str]:
    if value is None:
        return None
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _json_value(value: Any) -> Any:
    if value is None or isinstance(value, (list, dict)):
        return value
    try:
        return json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError):
        return value


class OAuthClientRepository:
    def __init__(self, *, sql: Optional[ForgeQueryPort] = None) -> None:
        self._sql = sql or ForgeMetaSQL()

    def create_client(self, *, payload: Dict[str, Any]) -> ForgeExecResult:
        params = dict(payload)
        params["redirect_uris"] = _json_or_none(params.get("redirect_uris"))
        params["grant_types"] = _json_or_none(params.get("grant_types"))
        params["response_types"] = _json_or_none(params.get("response_types"))
        params["contacts"] = _json_or_none(params.get("contacts"))
        return self._sql.execute_insert(
            """
            INSERT INTO oauth_clients (
              client_id,
              client_secret_hash,
              client_name,
              redirect_uris,
              grant_types,
              response_types,
              scope,
              token_endpoint_auth_method,
              client_uri,
              logo_uri,
              contacts,
              expires_at
            ) VALUES (
              :client_id,
              :client_secret_hash,
              :client_name,
              :redirect_uris,
              :grant_types,
              :response_types,
              :scope,
              :token_endpoint_auth_method,
              :client_uri,
              :logo_uri,
              :contacts,
              :expires_at
            )
            """,
            params,
        )

    def delete_expired_clients(self, *, now: datetime) -> int:
        return int(
            self._sql.execute_write(
                """
                DELETE FROM oauth_clients
                WHERE expires_at IS NOT NULL
                  AND expires_at < :now
                  AND revoked_at IS NULL
                """,
                {"now": now},
            )
            or 0
        )

    def get_active_client(self, *, client_id: str, now: datetime) -> Optional[Dict[str, Any]]:
        rows = self._sql.execute_query_mappings(
            """
            SELECT *
            FROM oauth_clients
            WHERE client_id = :client_id
              AND revoked_at IS NULL
              AND (expires_at IS NULL OR expires_at > :now)
            LIMIT 1
            """,
            {
                "client_id": str(client_id or "").strip(),
                "now": now,
            },
        )
        if not rows:
            return None
        row = dict(rows[0])
        for key in ("redirect_uris", "grant_types", "response_types", "contacts"):
            row[key] = _json_value(row.get(key))
        return row


__all__ = ["OAuthClientRepository"]
