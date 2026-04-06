from __future__ import annotations

import json
from typing import Any, Dict, Optional

JSON_LOAD_FALLBACK_ERRORS = (TypeError, ValueError, json.JSONDecodeError)


def safe_json_load(value: Optional[str]) -> Any:
    if not value:
        return None
    try:
        return json.loads(value)
    except JSON_LOAD_FALLBACK_ERRORS:
        return None


def base_response(
    *,
    workspace_table_id: int,
    full_name: Optional[str],
    model_table_id: Optional[int],
    column_name: str,
    limit: int,
    values: Any,
    sample_stats: Any,
    sample_ran_at: Any,
    error: Optional[str],
) -> Dict[str, Any]:
    return {
        "workspace_table_id": int(workspace_table_id),
        "full_name": full_name,
        "model_table_id": model_table_id,
        "column_name": column_name,
        "limit": int(limit),
        "values": values,
        "sample_stats": sample_stats,
        "sample_ran_at": sample_ran_at,
        "error": error,
    }
