from __future__ import annotations

import datetime
import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Literal, Mapping, Optional, Tuple

import pyarrow as pa
import pyarrow.ipc as pa_ipc
import requests

from app.ports.sql_executor import ForgeExecResult
from app.adapters.token_provider import TokenProvider
from app.services.base_service import build_url

logger = logging.getLogger(__name__)

ResultFormat = Literal["JSON_ARRAY", "JSON", "ARROW_STREAM"]
_TERMINAL_STATES = frozenset({"SUCCEEDED", "FAILED", "CANCELED"})
_STATEMENTS_API_PATH = "/api/2.0/sql/statements"


@dataclass(frozen=True)
class _QfStatementEnvelope:
    qf_statement_id: str
    status: Dict[str, Any]


class DatabricksForgeQueryPort:
    """Databricks SQL statements API executor."""

    def __init__(
        self,
        base_url: str,
        token_provider: TokenProvider,
        http: Optional[requests.Session] = None,
        default_warehouse_id: Optional[str] = None,
        default_catalog: Optional[str] = None,
        default_schema: Optional[str] = None,
        qf_poll_interval: float = 1.0,
        default_timeout_s: int = 300,
    ):
        self._base = base_url.rstrip("/")
        self._token_provider = token_provider
        self._http = http or requests.Session()
        self._warehouse = default_warehouse_id
        self._catalog = default_catalog
        self._schema = default_schema
        self._poll = float(qf_poll_interval)
        self._timeout = int(default_timeout_s)

        logger.debug("DBX executor init: default_timeout_s=%s poll=%s", default_timeout_s, qf_poll_interval)

    def submit_statement(
        self,
        sql: str,
        *,
        warehouse_id: Optional[str] = None,
        parameters: Optional[Mapping[str, Any]] = None,
        wait: bool = True,
        qf_timeout_s: Optional[int] = None,
        qf_result_fmt: ResultFormat = "JSON_ARRAY",
    ) -> Dict[str, Any]:
        payload = self._build_submit_payload(
            sql=sql,
            warehouse_id=warehouse_id,
            catalog=self._catalog,
            schema=self._schema,
            parameters=parameters,
            qf_result_fmt=qf_result_fmt,
        )

        logger.debug("Submitting SQL statement: %s", self._summarize_statement_payload(payload))
        response_payload = self._post_json(_STATEMENTS_API_PATH, payload)
        response_payload = self._with_statement_id_aliases(response_payload)

        # Log immediately if Databricks returns a terminal failure in the initial response
        initial_state = (response_payload.get("status") or {}).get("state")
        if initial_state == "FAILED":
            initial_error = self._extract_status_error_message(response_payload)
            logger.warning(
                "Databricks statement failed immediately: error=%s",
                initial_error,
            )

        if not wait:
            return response_payload

        qf_statement_id = self._extract_statement_id(response_payload)
        if not qf_statement_id:
            logger.error("No statement_id in response payload keys=%s", sorted(response_payload.keys()))
            raise ValueError("Databricks did not return a statement_id")

        effective_timeout = int(qf_timeout_s or self._timeout)
        logger.warning(
            "DBX submit_statement timeout: passed qf_timeout_s=%s, self._timeout=%s, effective=%s",
            qf_timeout_s,
            self._timeout,
            effective_timeout,
        )

        status_payload = self._wait_for_terminal(qf_statement_id, effective_timeout)
        state = (status_payload.get("status") or {}).get("state")
        logger.info("Statement %s finished with state=%s", qf_statement_id, state)
        if state != "SUCCEEDED":
            error_message = self._extract_status_error_message(status_payload)
            logger.warning(
                "Statement %s failed with state=%s error=%s",
                qf_statement_id,
                state,
                error_message,
            )
            raise RuntimeError(f"Databricks statement failed: {state} — {error_message}")

        if qf_result_fmt == "ARROW_STREAM":
            table = self.fetch_arrow_table(qf_statement_id)
            return {
                "qf_statement_id": qf_statement_id,
                "statement_id": qf_statement_id,
                "status": status_payload.get("status"),
                "qf_result_fmt": "ARROW_STREAM",
                "table": table,
                "rows": table.to_pylist(),
            }

        qf_result_rows = self.fetch_all_json(qf_statement_id)
        return {
            "qf_statement_id": qf_statement_id,
            "statement_id": qf_statement_id,
            "status": status_payload.get("status"),
            "qf_result_fmt": qf_result_fmt,
            "rows": qf_result_rows,
        }

    def submit_statement_async(
        self,
        sql: str,
        parameters: Mapping[str, Any],
        *,
        warehouse_id: Optional[str] = None,
        catalog: Optional[str] = None,
        schema: Optional[str] = None,
        qf_result_fmt: ResultFormat = "JSON_ARRAY",
    ) -> Dict[str, Any]:
        payload = self._build_submit_payload(
            sql=sql,
            warehouse_id=warehouse_id,
            catalog=(self._catalog if catalog is None else catalog),
            schema=(self._schema if schema is None else schema),
            parameters=parameters,
            qf_result_fmt=qf_result_fmt,
        )
        logger.debug("Submitting async SQL statement: %s", self._summarize_statement_payload(payload))
        response_payload = self._post_json(_STATEMENTS_API_PATH, payload)
        return self._with_statement_id_aliases(response_payload)

    def get_statement_status(self, qf_statement_id: str) -> Dict[str, Any]:
        response = self._get(f"{_STATEMENTS_API_PATH}/{qf_statement_id}")
        response.raise_for_status()
        return response.json()

    def cancel_statement(self, qf_statement_id: str) -> None:
        response = self._post(f"{_STATEMENTS_API_PATH}/{qf_statement_id}/cancel")
        if response.status_code not in (200, 202):
            response.raise_for_status()

    def execute_write(self, query: str, params: Optional[Mapping[str, Any]] = None) -> int:
        resp = self.submit_statement(query, parameters=params, qf_result_fmt="JSON_ARRAY")
        state = (resp.get("status") or {}).get("state")
        if state != "SUCCEEDED":
            raise RuntimeError(f"Databricks write failed: {resp}")
        return int(resp.get("rowcount") or 0)

    def execute_query_mappings(self, query: str, params: Optional[Mapping[str, Any]] = None) -> List[Dict[str, Any]]:
        resp = self.submit_statement(query, parameters=params, qf_result_fmt="ARROW_STREAM")
        rows = resp.get("rows")
        return rows if isinstance(rows, list) else []

    def execute_query(self, query: str, params: Optional[Mapping[str, Any]] = None) -> List[Tuple]:
        resp = self.submit_statement(query, parameters=params, qf_result_fmt="JSON_ARRAY")
        rows = resp.get("rows", [])
        return [tuple(row) for row in rows] if isinstance(rows, list) else []

    def execute_insert(self, query: str, params: Optional[Mapping[str, Any]] = None) -> ForgeExecResult:
        resp = self.submit_statement(query, parameters=params, qf_result_fmt="JSON_ARRAY")
        state = (resp.get("status") or {}).get("state")
        if state != "SUCCEEDED":
            raise RuntimeError(f"Databricks insert failed: {resp}")
        return ForgeExecResult(rowcount=int(resp.get("rowcount") or 0), lastrowid=None)

    def transaction(self):
        raise NotImplementedError("DatabricksForgeQueryPort does not support transactions")

    def poll_status(self, qf_statement_id: str) -> Dict[str, Any]:
        response = self._get(f"{_STATEMENTS_API_PATH}/{qf_statement_id}")
        response.raise_for_status()
        payload = response.json()
        state = (payload.get("status") or {}).get("state")
        logger.debug("Polled status for %s: state=%s", qf_statement_id, state)
        return payload

    def fetch_all_json(self, qf_statement_id: str) -> List[Any]:
        out: List[Any] = []
        for payload in self._iter_statement_result_pages(qf_statement_id):
            inline_rows = _rows_from_result_json(payload)
            if inline_rows:
                out.extend(inline_rows)

            for link in self._external_links(payload):
                url = link.get("external_link")
                if not url:
                    continue
                response = self._http.get(url, timeout=self._timeout)
                response.raise_for_status()
                out.extend(self._decode_external_json_text(response.text))

        return out

    def fetch_arrow_table(self, qf_statement_id: str) -> pa.Table:
        tables: List[pa.Table] = []

        for payload in self._iter_statement_result_pages(qf_statement_id):
            for link in self._external_links(payload):
                url = link.get("external_link")
                if not url:
                    continue
                response = self._http.get(url, timeout=self._timeout)
                response.raise_for_status()
                reader = pa_ipc.open_stream(pa.BufferReader(response.content))
                tables.append(reader.read_all())

        if not tables:
            return pa.table({})
        if len(tables) == 1:
            return tables[0]
        return pa.concat_tables(tables, promote=True)

    def fetch_all_arrow_rows(self, qf_statement_id: str) -> List[Dict[str, Any]]:
        return self.fetch_arrow_table(qf_statement_id).to_pylist()

    def cancel(self, qf_statement_id: str) -> None:
        response = self._post(f"{_STATEMENTS_API_PATH}/{qf_statement_id}/cancel")
        if response.status_code not in (200, 202, 409, 404):
            response.raise_for_status()

    def _build_submit_payload(
        self,
        *,
        sql: str,
        warehouse_id: Optional[str],
        catalog: Optional[str],
        schema: Optional[str],
        parameters: Optional[Mapping[str, Any]],
        qf_result_fmt: ResultFormat,
    ) -> Dict[str, Any]:
        warehouse = warehouse_id or self._warehouse
        if not warehouse:
            raise ValueError("No warehouse_id provided and no default_warehouse_id configured")

        payload: Dict[str, Any] = {
            "statement": sql,
            "warehouse_id": warehouse,
            "disposition": "EXTERNAL_LINKS",
            "format": qf_result_fmt,
        }
        if catalog is not None:
            payload["catalog"] = catalog
        if schema is not None:
            payload["schema"] = schema
        if parameters:
            payload["parameters"] = self._encode_parameters(parameters)
        return payload

    def _post_json(self, path: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        response = self._post(path, json=payload)
        logger.debug(
            "_post_json status=%s content_length=%s",
            response.status_code,
            len(response.content),
        )
        response.raise_for_status()
        try:
            return response.json()
        except Exception as exc:
            raise RuntimeError("Databricks returned a non-JSON response") from exc

    @staticmethod
    def _extract_status_error_message(payload: Dict[str, Any]) -> str:
        status = payload.get("status") or {}
        error = status.get("error") or {}
        if isinstance(error, dict):
            message = error.get("message")
            if isinstance(message, str) and message.strip():
                return message.strip()
        return "Unknown Databricks error"

    def _iter_statement_result_pages(self, qf_statement_id: str) -> Iterable[Dict[str, Any]]:
        next_path: Optional[str] = f"{_STATEMENTS_API_PATH}/{qf_statement_id}"
        while next_path:
            response = self._get(next_path)
            if response.status_code == 404:
                time.sleep(0.5)
                response = self._get(next_path)

            response.raise_for_status()
            payload = response.json()
            yield payload

            next_path = None
            for link in self._external_links(payload):
                next_path = link.get("next_chunk_internal_link")
                if next_path:
                    break

    @staticmethod
    def _external_links(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        result = payload.get("result") or {}
        links = result.get("external_links") or []
        return links if isinstance(links, list) else []

    @staticmethod
    def _decode_external_json_text(text: str) -> List[Any]:
        body = (text or "").strip()
        if not body:
            return []

        if body.startswith("["):
            parsed = json.loads(body)
            return parsed if isinstance(parsed, list) else [parsed]

        rows: List[Any] = []
        for line in body.splitlines():
            if line.strip():
                rows.append(json.loads(line))
        return rows

    @staticmethod
    def _extract_statement_id(payload: Dict[str, Any]) -> Optional[str]:
        statement_id = payload.get("statement_id") or payload.get("qf_statement_id")
        return str(statement_id) if statement_id else None

    @staticmethod
    def _with_statement_id_aliases(payload: Dict[str, Any]) -> Dict[str, Any]:
        statement_id = DatabricksForgeQueryPort._extract_statement_id(payload)
        if not statement_id:
            return payload

        out = dict(payload)
        out.setdefault("statement_id", statement_id)
        out.setdefault("qf_statement_id", statement_id)
        return out

    def _encode_parameters(self, parameters: Mapping[str, Any]) -> List[Dict[str, Any]]:
        encoded: List[Dict[str, Any]] = []

        for name, value in parameters.items():
            param = {"name": name}
            if value is None:
                param["type"] = "NULL"
                param["value"] = None
            elif isinstance(value, bool):
                param["type"] = "BOOLEAN"
                param["value"] = value
            elif isinstance(value, int):
                param["type"] = "INT"
                param["value"] = value
            elif isinstance(value, float):
                param["type"] = "DOUBLE"
                param["value"] = value
            elif isinstance(value, datetime.datetime):
                param["type"] = "TIMESTAMP"
                param["value"] = value.isoformat()
            elif isinstance(value, datetime.date):
                param["type"] = "DATE"
                param["value"] = value.isoformat()
            else:
                param["type"] = "STRING"
                param["value"] = str(value)

            encoded.append(param)

        return encoded

    def _wait_for_terminal(self, qf_statement_id: str, qf_timeout_s: int) -> Dict[str, Any]:
        qf_timeout_s = int(qf_timeout_s)
        deadline = time.time() + qf_timeout_s

        while True:
            payload = self.poll_status(qf_statement_id)
            state = (payload.get("status") or {}).get("state")
            if state in _TERMINAL_STATES:
                return payload

            if time.time() > deadline:
                self.cancel(qf_statement_id)
                raise TimeoutError(f"SQL statement {qf_statement_id} timed out after {qf_timeout_s}s")

            time.sleep(self._poll)

    def _resolve_token(self) -> str:
        provider = self._token_provider
        get_token: Optional[Callable[[], str]] = getattr(provider, "get_token", None)

        if callable(get_token):
            token = get_token()
        elif hasattr(provider, "token"):
            token = getattr(provider, "token")
        elif callable(provider):
            token = provider()
        else:
            raise TypeError("TokenProvider must expose get_token(), token attribute, or be callable")

        if not token:
            raise ValueError("TokenProvider returned an empty token")

        return token

    def _headers(self) -> Dict[str, str]:
        token = self._resolve_token()
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _get(self, path: str, params: Optional[Dict[str, Any]] = None) -> requests.Response:
        url = build_url(self._base, path)
        return self._http.get(url, headers=self._headers(), params=params, timeout=self._timeout)

    def _post(self, path: str, json: Optional[Dict[str, Any]] = None) -> requests.Response:
        url = build_url(self._base, path)
        return self._http.post(url, headers=self._headers(), json=json, timeout=self._timeout)

    def _summarize_statement_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        params = payload.get("parameters") or []
        return {
            "statement_len": len(str(payload.get("statement") or "")),
            "has_warehouse_id": bool(payload.get("warehouse_id")),
            "has_catalog": bool(payload.get("catalog")),
            "has_schema": bool(payload.get("schema")),
            "disposition": payload.get("disposition"),
            "format": payload.get("format"),
            "parameter_count": len(params) if isinstance(params, list) else 0,
        }


def _rows_from_result_json(payload: Dict[str, Any]) -> List[Any]:
    """
    Extract INLINE rows from Databricks result payload.

    - If data_array + manifest columns exist, returns list[dict]
    - Else if data_array exists but no columns, returns raw rows
    - Else if result is already a list, return that list
    - Else return []
    """
    result = payload.get("result")

    if isinstance(result, dict) and "data_array" in result:
        manifest = payload.get("manifest") or {}
        schema = manifest.get("schema") or {}
        columns = schema.get("columns") or []
        names = [c["name"] for c in columns if isinstance(c, dict) and "name" in c]
        if names:
            return [dict(zip(names, row)) for row in result["data_array"]]
        return result["data_array"]

    if isinstance(result, list):
        return result

    return []
