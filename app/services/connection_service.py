from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import requests

from app.config import SIGMA_BASE_URL
from app.decorators.validate import validate_params
from app.models.connection import Connection
from app.services.base_service import build_url, process_response
from app.services.base_token_manager import QF_SIGMA_TOKEN, forge_auth_headers

_SIGMA_TIMEOUT_SECONDS = 10


@dataclass(frozen=True)
class _ConnectionMatch:
    key: str
    prefix: str


def convert_to_conn(cnx: dict[str, Any]) -> Connection:
    auth_mode = "Oauth" if bool(cnx.get("useOauth")) else "Basic"
    return Connection(
        host=str(cnx.get("host") or ""),
        connection_id=str(cnx.get("connectionId") or ""),
        name=str(cnx.get("name") or ""),
        path="",
        authentication=auth_mode,
        access_token="",
    )


class ConnectionService:
    def get_connections(self) -> list[dict[str, Any]]:
        response = requests.get(
            build_url(SIGMA_BASE_URL, "connections"),
            headers=forge_auth_headers(QF_SIGMA_TOKEN),
            timeout=_SIGMA_TIMEOUT_SECONDS,
        )
        payload = process_response(response)
        entries = payload.get("entries") if isinstance(payload, dict) else []
        return [convert_to_conn(item).model_dump() for item in (entries or [])]

    @validate_params("organization")
    def get_connection_by_org(self, organization: str) -> list[dict[str, Any]]:
        return self._filter_connections(_ConnectionMatch(key="name", prefix=organization))

    @validate_params("host")
    def get_connection_by_host(self, host: str) -> list[dict[str, Any]]:
        return self._filter_connections(_ConnectionMatch(key="host", prefix=host))

    @validate_params("connection_id")
    def get_connection_by_id(self, connection_id: str) -> dict[str, Any]:
        response = requests.get(
            build_url(SIGMA_BASE_URL, "connections", connection_id),
            headers=forge_auth_headers(QF_SIGMA_TOKEN),
            timeout=_SIGMA_TIMEOUT_SECONDS,
        )
        payload = process_response(response)
        if not isinstance(payload, dict):
            payload = {}
        return convert_to_conn(payload).model_dump()

    def create_connection(self, cnx: Connection) -> dict[str, Any] | None:
        return None

    def _filter_connections(self, rule: _ConnectionMatch) -> list[dict[str, Any]]:
        prefix = (rule.prefix or "").strip()
        rows = self.get_connections()
        return [row for row in rows if str(row.get(rule.key) or "").startswith(prefix)]
