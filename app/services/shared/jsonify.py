from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, Iterable, List
from uuid import UUID


def jsonify_value(v: Any) -> Any:
    if v is None:
        return None

    # datetime/date -> isoformat
    if isinstance(v, (datetime, date)):
        return v.isoformat()

    # Decimal -> float (or str if you prefer)
    if isinstance(v, Decimal):
        return float(v)

    # UUID -> str
    if isinstance(v, UUID):
        return str(v)

    # bytes -> utf-8 (best-effort)
    if isinstance(v, (bytes, bytearray)):
        try:
            return v.decode("utf-8")
        except Exception:
            return str(v)

    # containers
    if isinstance(v, dict):
        return jsonify_dict(v)
    if isinstance(v, list):
        return [jsonify_value(x) for x in v]
    if isinstance(v, tuple):
        return [jsonify_value(x) for x in v]

    return v


def jsonify_dict(d: Dict[str, Any]) -> Dict[str, Any]:
    return {str(k): jsonify_value(v) for k, v in (d or {}).items()}


def jsonify_rows(rows: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [jsonify_dict(r) for r in (rows or [])]