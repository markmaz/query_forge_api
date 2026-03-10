from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from app.adapters.mysql_sql_executor import ForgeMetaSQL

logger = logging.getLogger(__name__)

BATCH_SIZE = 500


def infer_semantic_type(column_name: str) -> Optional[str]:
    name = (column_name or "").strip().lower()
    if not name:
        return None

    exact_map = {
        "city": "geography.city",
        "school_city": "geography.city",
        "name_of_county": "geography.county",
        "state": "geography.state",
        "zip": "geography.zip",
        "school_year": "time.school_year",
        "calendar_year": "time.calendar_year",
        "student_unique_id": "identifier.student_id",
        "first_name": "attribute.student.first_name",
        "last_name": "attribute.student.last_name",
        "race_ethnicity": "attribute.student.race",
        "days_enrolled": "metric.days_enrolled",
        "days_attended": "metric.days_attended",
    }
    if name in exact_map:
        return exact_map[name]

    if name.endswith("_date"):
        return "time.date"

    if name.startswith("is_"):
        suffix = name[3:] or "value"
        return f"flag.{suffix}"

    if name.startswith("k_"):
        return "identifier.surrogate_key"

    if name.endswith("_id"):
        return "identifier.surrogate_key"

    return None


def backfill_semantic_types(*, batch_size: int = BATCH_SIZE) -> Dict[str, int]:
    sql = ForgeMetaSQL()
    last_id = 0
    scanned = 0
    updated = 0

    while True:
        rows = sql.execute_query_mappings(
            """
            SELECT id, column_name, semantic_type
            FROM model_column
            WHERE id > :last_id
            ORDER BY id
            LIMIT :limit
            """,
            {"last_id": int(last_id), "limit": int(batch_size)},
        )
        if not rows:
            break

        updates: List[Dict[str, Any]] = []
        for row in rows:
            row_id = int(row["id"])
            col_name = str(row.get("column_name") or "")
            existing = row.get("semantic_type")
            scanned += 1
            last_id = row_id

            inferred = infer_semantic_type(col_name)
            if inferred is None:
                continue
            if isinstance(existing, str) and existing.strip():
                continue
            updates.append({"id": row_id, "semantic_type": inferred})

        if updates:
            with sql.transaction() as tx:
                for item in updates:
                    tx.execute_write(
                        """
                        UPDATE model_column
                        SET semantic_type = :semantic_type
                        WHERE id = :id
                          AND (semantic_type IS NULL OR semantic_type = '')
                        """,
                        item,
                    )
            updated += len(updates)
            logger.info("Backfill semantic_type batch updated=%s last_id=%s", len(updates), last_id)

    logger.info("Backfill semantic_type complete scanned=%s updated=%s", scanned, updated)
    return {"scanned": scanned, "updated": updated}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s - %(message)s")
    result = backfill_semantic_types()
    logger.info("Result: %s", result)
