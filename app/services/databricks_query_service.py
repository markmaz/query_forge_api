import json
import time
from typing import Any, Dict, Iterator, List, Optional

import requests

from app.config import DATABRICKS_STATEMENTS_URL
from app.services.base_service import build_url
from app.services.base_token_manager import DATABRICKS_TOKEN, get_headers

s = requests.Session()
s.headers.update(get_headers(DATABRICKS_TOKEN))

def submit_statement(sql: str,
                     databricks_host: str,
                     warehouse_id: str,
                     catalog: Optional[str] = None,
                     schema: Optional[str] = None,
                     disposition: str = "EXTERNAL_LINKS",
                     fmt: str = "JSON_ARRAY",
                     wait_timeout: str = "0s") -> Dict[str, Any]:
    """POST /api/2.0/sql/statements"""
    payload = {
        "warehouse_id": warehouse_id,
        "statement": sql,
        "disposition": disposition,     # "INLINE" or "EXTERNAL_LINKS"
        "format": fmt,                  # JSON_ARRAY | CSV | ARROW_STREAM (when using EXTERNAL_LINKS)
        "wait_timeout": wait_timeout,   # "0s" to return immediately and poll, or "5s"-"50s"
    }
    if catalog:
        payload["catalog"] = catalog
    if schema:
        payload["schema"] = schema
    r = s.post(build_url(databricks_host, DATABRICKS_STATEMENTS_URL), data=json.dumps(payload))
    r.raise_for_status()
    return r.json()

def get_statement(stmt_id: str, databricks_host: str) -> Dict[str, Any]:
    """GET /api/2.0/sql/statements/{statement_id}"""
    r = s.get(build_url(databricks_host,DATABRICKS_STATEMENTS_URL, stmt_id))
    r.raise_for_status()
    return r.json()

def wait_until_done(stmt_id: str, poll_interval_s: float = 2.0, timeout_s: float = 600.0) -> Dict[str, Any]:
    """Poll until SUCCEEDED/FAILED/CANCELED (or timeout)."""
    t0 = time.time()
    while True:
        info = get_statement(stmt_id)
        state = info.get("status", {}).get("state")
        if state in ("SUCCEEDED", "FAILED", "CANCELED"):
            return info
        if time.time() - t0 > timeout_s:
            raise TimeoutError(f"Statement {stmt_id} timed out; last state={state}")
        time.sleep(poll_interval_s)

def iter_inline_chunks(first_response: Dict[str, Any], databricks_host: str) -> Iterator[List[Dict[str, Any]]]:
    """
    For disposition=INLINE & format=JSON_ARRAY.
    Use next_chunk_internal_link to walk all chunks until API stops returning the link.
    """
    resp = first_response
    # Initial chunk’s rows live under result->data_array (for JSON_ARRAY) and schema in manifest.
    while True:
        rows = (resp.get("result") or {}).get("data_array") or []
        yield rows
        next_link = resp.get("next_chunk_internal_link")
        if not next_link:
            break
        # Follow next_chunk_internal_link with Authorization header
        r = s.get(f"{databricks_host}{next_link}")
        r.raise_for_status()
        resp = r.json()

def download_external_link(url: str) -> bytes:
    """
    For disposition=EXTERNAL_LINKS. Download the presigned URL *without* Authorization header.
    Returns raw bytes (JSON/CSV/Arrow depending on chosen format).
    """
    # Use a clean session or explicitly drop auth header
    r = requests.get(url, timeout=120)  # no auth header
    r.raise_for_status()
    return r.content

def iter_external_links(stmt_id: str, manifest: Dict[str, Any], databricks_host: str) -> Iterator[bytes]:
    """
    For disposition=EXTERNAL_LINKS. You typically:
      1) Read manifest["total_chunk_count"] (or iterate manifest["chunks"])
      2) GET each chunk: /api/2.0/sql/statements/{id}/result/chunks/{i}
      3) That per-chunk response returns presigned URLs (external links) to download.
    """
    # total_chunk_count may be present in manifest; otherwise len(manifest["chunks"])
    total = manifest.get("total_chunk_count")
    if total is None:
        total = len(manifest.get("chunks", []))

    for i in range(total):
        # GET chunk i (with Authorization) to obtain presigned links
        r = s.get(f"{databricks_host}/api/2.0/sql/statements/{stmt_id}/result/chunks/{i}")
        r.raise_for_status()
        chunk_meta = r.json()

        # Some responses use "external_links": [{"url": "..."}]; others use "external_link" singular.
        links = chunk_meta.get("external_links") or []
        if isinstance(links, dict):
            # Defensive: normalize if API returns a single object
            links = [links]
        if not links and "external_link" in chunk_meta:
            links = [{"url": chunk_meta["external_link"]}]

        if not links:
            # (Defensive) If the server decides to inline anyway, fall back to data_array
            data_inline = (chunk_meta.get("result") or {}).get("data_array")
            if data_inline is not None:
                yield json.dumps(data_inline).encode("utf-8")
                continue

        for link in links:
            url = link.get("url") or link.get("external_link")
            if not url:
                continue
            yield download_external_link(url)

def run_and_collect_all(sql: str,
                        catalog: Optional[str] = None,
                        schema: Optional[str] = None,
                        disposition: str = "EXTERNAL_LINKS",
                        fmt: str = "JSON_ARRAY") -> List[Dict[str, Any]]:
    """
    Executes a query and returns *all* rows as a list of dicts if JSON.
    For CSV/Arrow, returns raw payloads per chunk (you can adapt).
    """
    create = submit_statement(sql, catalog=catalog, schema=schema,
                              disposition=disposition, fmt=fmt, wait_timeout="0s")
    stmt_id = create["statement_id"]

    final = wait_until_done(stmt_id)

    status = final.get("status", {}).get("state")
    if status != "SUCCEEDED":
        raise RuntimeError(f"Statement failed: {final.get('status')}")

    manifest = final.get("manifest", {})  # includes schema, chunking info, format, etc.

    if disposition.upper() == "INLINE":
        # Collect inline JSON rows from all chunks
        all_rows: List[Dict[str, Any]] = []
        for rows in iter_inline_chunks(final):
            all_rows.extend(rows)
        return all_rows

    # EXTERNAL_LINKS
    if fmt == "JSON_ARRAY":
        all_rows: List[Dict[str, Any]] = []
        for payload in iter_external_links(stmt_id, manifest):
            # Each payload is JSON containing an array of rows (format JSON_ARRAY)
            all_rows.extend(json.loads(payload))
        return all_rows

    # CSV or ARROW_STREAM: return raw payload chunks
    raw_chunks = list(iter_external_links(stmt_id, manifest))
    return raw_chunks
