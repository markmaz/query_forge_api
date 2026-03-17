from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

QF_EXCEL_MAX_ROWS = 1_048_576
QF_CSV_MAX_ROWS = 5_000_000   # practical CSV size limit for large datasets
_ROWCOUNT_CACHE_TTL_S = 300


@dataclass(slots=True)
class _CacheEntry:
    expires_at: float
    total_rows: int


_rowcount_cache: dict[str, _CacheEntry] = {}


def build_qf_export_policy(total_rows: int) -> Dict[str, Any]:
    n = int(total_rows or 0)
    excel_ok = n <= QF_EXCEL_MAX_ROWS
    csv_ok = n <= QF_CSV_MAX_ROWS
    return {
        "excel": {
            "maxRows": QF_EXCEL_MAX_ROWS,
            "allowed": excel_ok,
            "reason": None if excel_ok else "EXCEL_ROW_LIMIT",
        },
        "csv": {
            "maxRows": QF_CSV_MAX_ROWS,
            "allowed": csv_ok,
            "reason": None if csv_ok else "CSV_ROW_LIMIT",
        },
        "json": {"allowed": True},
    }


def qf_rowcount_signature(sql: str, params: Dict[str, Any]) -> str:
    payload = {"sql": sql or "", "params": params or {}}
    encoded = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def fetch_cached_rowcount(signature: str) -> Optional[int]:
    if not signature:
        return None
    entry = _rowcount_cache.get(signature)
    if entry is None:
        return None
    if entry.expires_at < time.time():
        _rowcount_cache.pop(signature, None)
        return None
    return entry.total_rows


def store_cached_rowcount(signature: str, total_rows: int) -> None:
    if not signature:
        return
    _rowcount_cache[signature] = _CacheEntry(
        expires_at=time.time() + _ROWCOUNT_CACHE_TTL_S,
        total_rows=int(total_rows),
    )


def clear_qf_rowcount_cache() -> None:
    _rowcount_cache.clear()
