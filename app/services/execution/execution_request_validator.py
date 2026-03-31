from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional

from app.exceptions.forge_error import ForgeError


@dataclass(frozen=True)
class ExecutionRequest:
    kind: str
    sql_json: Optional[Dict[str, Any]]
    raw_sql: Optional[str]
    limit: int
    offset: int


class ExecutionRequestValidator:
    def __init__(
        self,
        *,
        assert_no_disallowed_client_sql_fields: Callable[[Dict[str, Any]], None],
        int_from_payload: Callable[[Any, str], Optional[int]],
        int_from_args: Callable[[Dict[str, Any], str, int], int],
    ) -> None:
        self._assert_no_disallowed_client_sql_fields = assert_no_disallowed_client_sql_fields
        self._int_from_payload = int_from_payload
        self._int_from_args = int_from_args

    def validate_start(
        self,
        payload: Dict[str, Any],
        query_args: Dict[str, Any],
    ) -> ExecutionRequest:
        self._assert_no_disallowed_client_sql_fields(payload)

        sql_json = payload.get("sqlJson") or payload.get("sql_json")
        raw_sql = payload.get("rawSql") or payload.get("raw_sql")
        if sql_json is not None and not isinstance(sql_json, dict):
            raise ForgeError("sqlJson must be an object", status_code=400)

        kind = str(payload.get("kind") or "").strip()
        if not kind and isinstance(sql_json, dict):
            kind = "query_builder"
        if not kind and isinstance(raw_sql, str) and raw_sql.strip():
            kind = "query_builder_sql"
        if kind not in {"query_builder", "query_builder_sql"}:
            raise ForgeError("kind must be query_builder or query_builder_sql", status_code=400)

        limit_from_payload = self._int_from_payload(payload.get("limit"), "limit")
        offset_from_payload = self._int_from_payload(payload.get("offset"), "offset")
        limit = limit_from_payload if limit_from_payload is not None else self._int_from_args(query_args, "limit", 200)
        offset = offset_from_payload if offset_from_payload is not None else self._int_from_args(query_args, "offset", 0)

        if kind == "query_builder_sql":
            if sql_json is not None:
                raise ForgeError("sqlJson is not allowed when kind=query_builder_sql", status_code=400)
            sql_text = str(raw_sql or "").strip()
            if not sql_text:
                raise ForgeError("rawSql is required", status_code=400)
            return ExecutionRequest(kind=kind, sql_json=None, raw_sql=sql_text, limit=limit, offset=offset)

        if sql_json is None:
            raise ForgeError("sqlJson is required", status_code=400)
        return ExecutionRequest(kind=kind, sql_json=sql_json, raw_sql=None, limit=limit, offset=offset)
