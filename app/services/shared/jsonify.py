from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Iterable
from uuid import UUID


def serialize_cell(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, (bytes, bytearray)):
        try:
            return value.decode("utf-8")
        except Exception:
            return str(value)
    if isinstance(value, dict):
        return serialize_record(value)
    if isinstance(value, (list, tuple)):
        return [serialize_cell(item) for item in value]
    return value


def serialize_record(payload: dict[str, Any]) -> dict[str, Any]:
    return {str(key): serialize_cell(val) for key, val in (payload or {}).items()}


def serialize_result_rows(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [serialize_record(row) for row in (rows or [])]
