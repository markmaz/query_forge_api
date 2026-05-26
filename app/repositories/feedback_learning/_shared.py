from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, Mapping, Optional


def parse_json_object(value: Any) -> Optional[Dict[str, Any]]:
    if value is None:
        return None
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, (bytes, bytearray)):
        try:
            value = bytes(value).decode("utf-8", errors="ignore")
        except (TypeError, ValueError):
            return None
    if isinstance(value, str):
        text = value.strip()
        if text == "":
            return None
        try:
            parsed = json.loads(text)
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
        if isinstance(parsed, dict):
            return parsed
    return None


def serialize_json_object(payload: Optional[Mapping[str, Any]]) -> Optional[str]:
    if payload is None:
        return None
    return json.dumps(dict(payload), ensure_ascii=True, separators=(",", ":"))


def normalize_optional_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def normalize_datetime(value: Any) -> Optional[datetime]:
    if value is None or isinstance(value, datetime):
        return value
    if isinstance(value, str):
        raw = value.strip()
        if raw == "":
            return None
        direct = datetime.fromisoformat(raw.replace("Z", "+00:00").replace(" ", "T"))
        return direct
    raise TypeError(f"Unsupported datetime value: {value!r}")
