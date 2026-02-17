from __future__ import annotations

import datetime
import json
import logging
import time
from typing import Any, Callable, Dict, List, Literal, Mapping, Optional, Tuple

import pyarrow as pa
import pyarrow.ipc as pa_ipc
import requests

from app.config import DATABRICKS_STATEMENTS_URL
from app.ports.sql_executor import ExecuteResult
from app.ports.token_manager import TokenManager
from app.services.base_service import build_url

logger = logging.getLogger(__name__)

ResultFormat = Literal["JSON_ARRAY", "JSON", "ARROW_STREAM"]


class DatabricksSQLExecutor:
    """
    Databricks /api/2.0/sql/statements executor.
    - Submits a statement
    - Polls until completion
    - Retrieves results as JSON (INLINE + external_links) or Arrow via external_links

    IMPORTANT:
      - Databricks "JSON_ARRAY" rows are arrays (positional), not dicts.
      - If you want dict rows without relying on manifest/schema metadata, use ARROW_STREAM
        and convert via pyarrow.Table.to_pylist().
    """

    def __init__(
        self,
        base_url: str,
        token_provider: TokenManager,
        http: Optional[requests.Session] = None,
        default_warehouse_id: Optional[str] = None,
        default_catalog: Optional[str] = None,
        default_schema: Optional[str] = None,
        poll_interval_s: float = 1.0,
        default_timeout_s: int = 300,
    ):
        self._base = base_url.rstrip("/")
        self._token_provider = token_provider
        self._http = http or requests.Session()
        self._warehouse = default_warehouse_id
        self._catalog = default_catalog
        self._schema = default_schema
        self._poll = poll_interval_s
        self._timeout = default_timeout_s

        logger.debug("DBX executor init: default_timeout_s=%s poll=%s", default_timeout_s, poll_interval_s)

    # ---------- Protocol methods ----------

    def submit_statement(
        self,
        sql: str,
        *,
        warehouse_id: Optional[str] = None,
        parameters: Optional[Mapping[str, Any]] = None,
        wait: bool = True,
        timeout_s: Optional[int] = None,
        result_format: ResultFormat = "JSON_ARRAY",
    ) -> Dict[str, Any]:
        """
        Submit a SQL statement.

        result_format:
            - "JSON_ARRAY": rows are positional arrays (often from external_links)
            - "JSON": may still be positional depending on how you fetch; do not assume dict rows
            - "ARROW_STREAM": returns a pyarrow.Table + also returns dict rows via table.to_pylist()
        """
        wh = warehouse_id or self._warehouse
        if not wh:
            raise ValueError("No warehouse_id provided and no default_warehouse_id configured")

        payload: Dict[str, Any] = {
            "statement": sql,
            "warehouse_id": wh,
            "catalog": self._catalog,
            "schema": self._schema,
            "disposition": "EXTERNAL_LINKS",
            # ✅ always be explicit about the result format
            "format": result_format,
        }

        if parameters:
            payload["parameters"] = self._encode_parameters(parameters)

        logger.debug("Submitting SQL statement: %s", self._summarize_statement_payload(payload))
        r = self._post(DATABRICKS_STATEMENTS_URL, json=payload)
        r.raise_for_status()
        data = r.json()

        if not wait:
            return data

        statement_id = data.get("statement_id")
        if not statement_id:
            logger.error("No statement_id in response: %s", data)
            raise ValueError("Databricks did not return a statement_id")

        effective_timeout = timeout_s or self._timeout
        logger.warning(
            "DBX submit_statement timeout: passed timeout_s=%s, self._timeout=%s, effective=%s",
            timeout_s, self._timeout, effective_timeout
)

        status = self._wait_for_terminal(statement_id, timeout_s or self._timeout)
        state = (status.get("status") or {}).get("state")
        logger.info("Statement %s finished with state=%s", statement_id, state)
        if state != "SUCCEEDED":
            return status

        if result_format == "ARROW_STREAM":
            table = self.fetch_arrow_table(statement_id)
            # ✅ Provide dict rows for callers that don't want to deal with Arrow
            rows = table.to_pylist()
            return {
                "statement_id": statement_id,
                "status": status.get("status"),
                "result_format": "ARROW_STREAM",
                "table": table,   # pyarrow.Table
                "rows": rows,     # List[Dict[str, Any]]
            }

        # JSON / JSON_ARRAY
        rows_any = self.fetch_all_json(statement_id)
        return {
            "statement_id": statement_id,
            "status": status.get("status"),
            "result_format": result_format,
            "rows": rows_any,
        }

    def submit_statement_async(
        self,
        sql: str,
        parameters: Mapping[str, Any],
        *,
        warehouse_id: Optional[str] = None,
        catalog: Optional[str] = None,
        schema: Optional[str] = None,
        result_format: ResultFormat = "JSON_ARRAY",
    ) -> Dict[str, Any]:
        wh = warehouse_id or self._warehouse
        if not wh:
            raise ValueError("No warehouse_id provided and no default_warehouse_id configured")

        payload: Dict[str, Any] = {
            "statement": sql,
            "warehouse_id": wh,
            "catalog": catalog if catalog is not None else self._catalog,
            "schema": schema if schema is not None else self._schema,
            "disposition": "EXTERNAL_LINKS",
            "format": result_format,
        }

        if parameters:
            payload["parameters"] = self._encode_parameters(parameters)

        logger.debug("Submitting async SQL statement: %s", self._summarize_statement_payload(payload))
        r = self._post(DATABRICKS_STATEMENTS_URL, json=payload)
        r.raise_for_status()
        return r.json()

    def get_statement_status(self, statement_id: str) -> Dict[str, Any]:
        r = self._get(f"{DATABRICKS_STATEMENTS_URL}/{statement_id}")
        r.raise_for_status()
        return r.json()

    def cancel_statement(self, statement_id: str) -> None:
        r = self._post(f"{DATABRICKS_STATEMENTS_URL}/{statement_id}/cancel")
        if r.status_code not in (200, 202):
            r.raise_for_status()

    def execute_write(self, query: str, params: Optional[Mapping[str, Any]] = None) -> int:
        resp = self.submit_statement(query, parameters=params, result_format="JSON_ARRAY")
        state = (resp.get("status") or {}).get("state")
        if state != "SUCCEEDED":
            raise RuntimeError(f"Databricks write failed: {resp}")
        rowcount = resp.get("rowcount")
        return int(rowcount or 0)

    def execute_query_mappings(self, query: str, params: Optional[Mapping[str, Any]] = None) -> List[Dict[str, Any]]:
        resp = self.submit_statement(query, parameters=params, result_format="ARROW_STREAM")
        rows = resp.get("rows")
        return rows if isinstance(rows, list) else []

    def execute_query(self, query: str, params: Optional[Mapping[str, Any]] = None) -> List[Tuple]:
        resp = self.submit_statement(query, parameters=params, result_format="JSON_ARRAY")
        rows = resp.get("rows", [])
        return [tuple(r) for r in rows] if isinstance(rows, list) else []

    def execute_insert(self, query: str, params: Optional[Mapping[str, Any]] = None) -> ExecuteResult:
        resp = self.submit_statement(query, parameters=params, result_format="JSON_ARRAY")
        state = (resp.get("status") or {}).get("state")
        if state != "SUCCEEDED":
            raise RuntimeError(f"Databricks insert failed: {resp}")
        rowcount = resp.get("rowcount")
        return ExecuteResult(rowcount=int(rowcount or 0), lastrowid=None)

    def transaction(self):
        raise NotImplementedError("DatabricksSQLExecutor does not support transactions")

    def poll_status(self, statement_id: str) -> Dict[str, Any]:
        r = self._get(f"{DATABRICKS_STATEMENTS_URL}/{statement_id}")
        r.raise_for_status()
        payload = r.json()
        state = (payload.get("status") or {}).get("state")
        logger.debug("Polled status for %s: state=%s", statement_id, state)
        return payload

    def fetch_all_json(self, statement_id: str) -> List[Any]:
        """
        Returns a list of rows from INLINE data_array + external_links JSON chunks.
        WARNING: For JSON_ARRAY, rows may be lists (positional), not dicts.
        """
        out: List[Any] = []
        next_path: Optional[str] = f"{DATABRICKS_STATEMENTS_URL}/{statement_id}"

        while next_path:
            r = self._get(next_path)

            if r.status_code == 404:
                time.sleep(0.5)
                r = self._get(next_path)

            r.raise_for_status()
            payload = r.json()

            rows = _rows_from_result_json(payload)
            if rows:
                out.extend(rows)

            result = payload.get("result") or {}
            external_links = result.get("external_links") or []

            for link in external_links:
                url = link.get("external_link")
                if not url:
                    continue
                lr = self._http.get(url, timeout=self._timeout)
                lr.raise_for_status()
                text = lr.text.strip()
                if not text:
                    continue

                if text.startswith("["):
                    # could be list[dict] OR list[list]
                    out.extend(json.loads(text))
                else:
                    # newline-delimited JSON objects
                    for line in text.splitlines():
                        if line.strip():
                            out.append(json.loads(line))

            next_internal: Optional[str] = None
            for link in external_links:
                next_internal = link.get("next_chunk_internal_link")
                if next_internal:
                    break

            next_path = next_internal

        return out

    def fetch_arrow_table(self, statement_id: str) -> pa.Table:
        tables: List[pa.Table] = []
        next_path: Optional[str] = f"{DATABRICKS_STATEMENTS_URL}/{statement_id}"

        while next_path:
            r = self._get(next_path)

            if r.status_code == 404:
                time.sleep(0.5)
                r = self._get(next_path)

            r.raise_for_status()
            payload = r.json()

            result = payload.get("result") or {}
            external_links = result.get("external_links") or []

            for link in external_links:
                url = link.get("external_link")
                if not url:
                    continue
                lr = self._http.get(url, timeout=self._timeout)
                lr.raise_for_status()

                reader = pa_ipc.open_stream(pa.BufferReader(lr.content))
                tables.append(reader.read_all())

            next_internal: Optional[str] = None
            for link in external_links:
                next_internal = link.get("next_chunk_internal_link")
                if next_internal:
                    break

            next_path = next_internal

        if not tables:
            return pa.table({})

        if len(tables) == 1:
            return tables[0]

        return pa.concat_tables(tables, promote=True)

    def fetch_all_arrow_rows(self, statement_id: str) -> List[Dict[str, Any]]:
        """
        Convenience: fetch Arrow and return list[dict] rows (column names preserved).
        """
        tbl = self.fetch_arrow_table(statement_id)
        return tbl.to_pylist()

    def cancel(self, statement_id: str) -> None:
        r = self._post(f"{DATABRICKS_STATEMENTS_URL}/{statement_id}/cancel")
        if r.status_code not in (200, 202, 409, 404):
            r.raise_for_status()

    # ---------- Internals ----------

    def _encode_parameters(self, parameters: Mapping[str, Any]) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for name, value in parameters.items():
            p = {"name": name}

            if value is None:
                p["type"] = "NULL"
                p["value"] = None
                out.append(p)
                continue

            if isinstance(value, bool):
                p["type"] = "BOOLEAN"
                p["value"] = value
                out.append(p)
                continue

            if isinstance(value, int):
                p["type"] = "INT"
                p["value"] = value
                out.append(p)
                continue

            if isinstance(value, float):
                p["type"] = "DOUBLE"
                p["value"] = value
                out.append(p)
                continue

            if isinstance(value, datetime.datetime):
                p["type"] = "TIMESTAMP"
                p["value"] = value.isoformat()
                out.append(p)
                continue

            if isinstance(value, datetime.date):
                p["type"] = "DATE"
                p["value"] = value.isoformat()
                out.append(p)
                continue

            p["type"] = "STRING"
            p["value"] = str(value)
            out.append(p)

        return out

    def _wait_for_terminal(self, statement_id: str, timeout_s: int) -> Dict[str, Any]:
        timeout_s = int(timeout_s)
        deadline = time.time() + timeout_s
        while True:
            status = self.poll_status(statement_id)
            s = (status.get("status") or {}).get("state")

            if s in {"SUCCEEDED", "FAILED", "CANCELED"}:
                return status

            if time.time() > deadline:
                self.cancel(statement_id)
                raise TimeoutError(f"SQL statement {statement_id} timed out after {timeout_s}s")

            time.sleep(self._poll)

    def _resolve_token(self) -> str:
        provider = self._token_provider
        get_token: Optional[Callable[[], str]] = getattr(provider, "get_token", None)
        if callable(get_token):
            tok = get_token()
        elif hasattr(provider, "token"):
            tok = getattr(provider, "token")
        elif callable(provider):
            tok = provider()
        else:
            raise TypeError("TokenManager must expose get_token(), token attribute, or be callable")

        if not tok:
            raise ValueError("TokenManager returned an empty token")

        return tok

    def _headers(self) -> Dict[str, str]:
        tok = self._resolve_token()
        return {
            "Authorization": f"Bearer {tok}",
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
        parameters = payload.get("parameters") or []
        return {
            "statement_len": len(str(payload.get("statement") or "")),
            "has_warehouse_id": bool(payload.get("warehouse_id")),
            "has_catalog": bool(payload.get("catalog")),
            "has_schema": bool(payload.get("schema")),
            "disposition": payload.get("disposition"),
            "format": payload.get("format"),
            "parameter_count": len(parameters) if isinstance(parameters, list) else 0,
        }


def _rows_from_result_json(payload: Dict[str, Any]) -> List[Any]:
    """
    Attempt to extract INLINE rows.
    - If data_array + manifest columns exist, returns list[dict]
    - Otherwise returns [] (external_links handled by fetch_all_json)
    """
    result = payload.get("result")

    if isinstance(result, dict) and "data_array" in result:
        manifest = payload.get("manifest") or {}
        schema = manifest.get("schema") or {}
        columns = schema.get("columns") or []
        cols = [c["name"] for c in columns if isinstance(c, dict) and "name" in c]
        if cols:
            return [dict(zip(cols, row)) for row in result["data_array"]]
        # no column metadata -> can't map safely
        return result["data_array"]

    if isinstance(result, list):
        return result

    return []
