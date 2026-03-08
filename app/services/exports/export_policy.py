from __future__ import annotations

import hashlib
import json
import time
from typing import Any, Dict, Optional

QF_EXCEL_MAX_ROWS = 1_048_576
_ROWCOUNT_CACHE_TTL_S = 300

_rowcount_cache: dict[str, tuple[float, int]] = {}


def build_qf_export_policy(total_rows: int) -> Dict[str, Any]:
    allowed = int(total_rows or 0) <= QF_EXCEL_MAX_ROWS
    return {
        "excel": {
            "maxRows": QF_EXCEL_MAX_ROWS,
            "allowed": allowed,
            "reason": None if allowed else "EXCEL_ROW_LIMIT",
        },
        "csv": {"allowed": True},
    }


def qf_rowcount_signature(sql: str, params: Dict[str, Any]) -> str:
    payload = {"sql": sql or "", "params": params or {}}
    encoded = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def fetch_cached_rowcount(signature: str) -> Optional[int]:
    if not signature:
        return None
    entry = _rowcount_cache.get(signature)
    if not entry:
        return None
    expires_at, total_rows = entry
    if expires_at < time.time():
        _rowcount_cache.pop(signature, None)
        return None
    return total_rows


def store_cached_rowcount(signature: str, total_rows: int) -> None:
    if not signature:
        return
    _rowcount_cache[signature] = (time.time() + _ROWCOUNT_CACHE_TTL_S, int(total_rows))


def clear_qf_rowcount_cache() -> None:
    _rowcount_cache.clear()
