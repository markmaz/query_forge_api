from __future__ import annotations

from typing import Any, Dict

from app.services.shared.jsonify import serialize_result_rows


def collapse_domain_summary_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id: Dict[int, Dict[str, Any]] = {}

    for row in rows:
        domain_id = int(row["domain_id"])
        if domain_id not in by_id:
            by_id[domain_id] = {
                "id": domain_id,
                "table_count": int(row["table_count"] or 0),
                "table_sample": [],
            }
        sample_table_name = row.get("sample_table_name")
        if sample_table_name:
            by_id[domain_id]["table_sample"].append(str(sample_table_name))

    return serialize_result_rows(list(by_id.values()))
