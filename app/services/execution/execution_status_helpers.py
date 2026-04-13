from __future__ import annotations

import datetime
from typing import Any, Dict, Optional


def utc_now_iso() -> str:
    return datetime.datetime.now(datetime.UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def normalize_status_dict(raw: Any) -> Optional[Dict[str, Any]]:
    if isinstance(raw, dict):
        out = dict(raw)
        if isinstance(out.get("status"), dict):
            status = dict(out.get("status") or {})
            if "state" in status or "error" in status:
                return status
        if "state" in out or "error" in out:
            return out
    if isinstance(raw, str) and raw.strip():
        return {"state": raw.strip()}
    return None
