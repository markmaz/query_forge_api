from __future__ import annotations

import json
import time
from typing import Any, Dict, Iterator, List, Optional

import requests

from app.config import DATABRICKS_STATEMENTS_URL
from app.services.base_service import build_url
from app.services.base_token_manager import QF_DATABRICKS_TOKEN, forge_auth_headers

s = requests.Session()
s.headers.update(forge_auth_headers(QF_DATABRICKS_TOKEN))


def submit_statement(
    sql: str,
    databricks_host: str,
    warehouse_id: str,
    catalog: Optional[str] = None,
    schema: Optional[str] = None,
    disposition: str = "EXTERNAL_LINKS",
    fmt: str = "JSON_ARRAY",
    wait_timeout: str = "0s",
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "warehouse_id": warehouse_id,
        "statement": sql,
        "disposition": disposition,
        "format": fmt,
        "wait_timeout": wait_timeout,
    }
    if catalog:
        payload["catalog"] = catalog
    if schema:
        payload["schema"] = schema

    response = s.post(build_url(databricks_host, DATABRICKS_STATEMENTS_URL), data=json.dumps(payload))
    response.raise_for_status()
    return response.json()


def get_statement(stmt_id: str, databricks_host: str | None = None) -> Dict[str, Any]:
    if not databricks_host:
        raise ValueError("databricks_host is required")
    response = s.get(build_url(databricks_host, DATABRICKS_STATEMENTS_URL, stmt_id))
    response.raise_for_status()
    return response.json()


def wait_until_done(
    stmt_id: str,
    qf_poll_interval: float = 2.0,
    qf_timeout_s: float = 600.0,
    databricks_host: str | None = None,
) -> Dict[str, Any]:
    started_at = time.time()
    while True:
        info = get_statement(stmt_id) if databricks_host is None else get_statement(stmt_id, databricks_host)
        state = (info.get("status") or {}).get("state")
        if state in {"SUCCEEDED", "FAILED", "CANCELED"}:
            return info

        if time.time() - started_at > qf_timeout_s:
            raise TimeoutError(f"Statement {stmt_id} timed out; last state={state}")
        time.sleep(qf_poll_interval)


def iter_inline_chunks(
    first_response: Dict[str, Any],
    databricks_host: str | None = None,
) -> Iterator[List[Dict[str, Any]]]:
    cursor = first_response
    while True:
        rows = (cursor.get("result") or {}).get("data_array") or []
        yield rows

        next_link = cursor.get("next_chunk_internal_link")
        if not next_link:
            break
        if not databricks_host:
            raise ValueError("databricks_host is required when following next_chunk_internal_link")

        chunk_response = s.get(f"{databricks_host}{next_link}")
        chunk_response.raise_for_status()
        cursor = chunk_response.json()


def download_external_link(url: str) -> bytes:
    response = requests.get(url, timeout=120)
    response.raise_for_status()
    return response.content


def iter_external_links(
    stmt_id: str,
    manifest: Dict[str, Any],
    databricks_host: str | None = None,
) -> Iterator[bytes]:
    if not databricks_host:
        raise ValueError("databricks_host is required")

    total_chunks = manifest.get("total_chunk_count")
    if total_chunks is None:
        total_chunks = len(manifest.get("chunks", []))

    for idx in range(int(total_chunks)):
        chunk = s.get(f"{databricks_host}/api/2.0/sql/statements/{stmt_id}/result/chunks/{idx}")
        chunk.raise_for_status()
        chunk_payload = chunk.json()

        links = chunk_payload.get("external_links") or []
        if isinstance(links, dict):
            links = [links]
        if not links and "external_link" in chunk_payload:
            links = [{"url": chunk_payload.get("external_link")}]

        if not links:
            inline = (chunk_payload.get("result") or {}).get("data_array")
            if inline is not None:
                yield json.dumps(inline).encode("utf-8")
            continue

        for link in links:
            url = link.get("url") or link.get("external_link")
            if url:
                yield download_external_link(url)


def run_and_collect_all(
    sql: str,
    catalog: Optional[str] = None,
    schema: Optional[str] = None,
    disposition: str = "EXTERNAL_LINKS",
    fmt: str = "JSON_ARRAY",
    *,
    databricks_host: str | None = None,
    warehouse_id: str | None = None,
) -> List[Any]:
    if databricks_host and warehouse_id:
        created = submit_statement(
            sql,
            databricks_host=databricks_host,
            warehouse_id=warehouse_id,
            catalog=catalog,
            schema=schema,
            disposition=disposition,
            fmt=fmt,
            wait_timeout="0s",
        )
    else:
        # Legacy call shape maintained for backward compatibility with older callsites/tests.
        created = submit_statement(  # type: ignore[call-arg]
            sql,
            catalog=catalog,
            schema=schema,
            disposition=disposition,
            fmt=fmt,
            wait_timeout="0s",
        )
    statement_id = created["qf_statement_id"]

    final = wait_until_done(statement_id)
    status = (final.get("status") or {}).get("state")
    if status != "SUCCEEDED":
        raise RuntimeError(f"Statement failed: {final.get('status')}")

    manifest = final.get("manifest", {})

    if disposition.upper() == "INLINE":
        all_rows: List[Dict[str, Any]] = []
        for chunk_rows in iter_inline_chunks(final):
            all_rows.extend(chunk_rows)
        return all_rows

    if fmt == "JSON_ARRAY":
        all_rows: List[Dict[str, Any]] = []
        for payload in (
            iter_external_links(statement_id, manifest, databricks_host)
            if databricks_host
            else iter_external_links(statement_id, manifest)
        ):
            all_rows.extend(json.loads(payload))
        return all_rows

    return list(
        iter_external_links(statement_id, manifest, databricks_host)
        if databricks_host
        else iter_external_links(statement_id, manifest)
    )
