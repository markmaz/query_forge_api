from __future__ import annotations

from typing import Any, Dict, Iterable, List

from app.services.shared.jsonify import serialize_result_rows


def serialize_workspace_table_rows(rows: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    payload = []
    for row in rows:
        shaped = dict(row)
        shaped["model_table_id"] = shaped.get("workspace_table_id")
        shaped["model_table_name"] = shaped.get("table_label")
        payload.append(shaped)
    return serialize_result_rows(payload)
