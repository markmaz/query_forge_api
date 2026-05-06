from __future__ import annotations

import json
from typing import Any, Optional


def json_or_none(value: Any) -> Optional[str]:
    if value is None:
        return None
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def json_value(value: Any) -> Any:
    if value is None or isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError):
        return value


def bool_value(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def lastrowid(result: Any) -> int:
    return int(getattr(result, "lastrowid", None) or 0)
