from __future__ import annotations

import argparse
import json
import logging
from typing import Any, Dict, List, Optional

from app.adapters.mysql_sql_executor import MySQLSQLExecutor

logger = logging.getLogger(__name__)

DEFAULT_BATCH_SIZE = 500
DEFAULT_SOURCE = "manual"


def backfill_model_column_semantics(
    *,
    vertical_norm: Optional[str] = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
    dry_run: bool = False,
    force: bool = False,
    source: str = DEFAULT_SOURCE,
) -> Dict[str, Any]:
    sql = MySQLSQLExecutor()

    vertical = _normalize_vertical(vertical_norm)
    source_value = str(source or DEFAULT_SOURCE).strip().lower() or DEFAULT_SOURCE

    last_id = 0
    scanned = 0
    matched = 0
    updated = 0

    while True:
        rows = _load_best_rows(
            sql=sql,
            last_id=last_id,
            limit=batch_size,
            vertical_norm=vertical,
            force=force,
        )
        if not rows:
            break

        scanned += len(rows)
        updates: List[Dict[str, Any]] = []
        for row in rows:
            model_column_id = int(row["model_column_id"])
            last_id = max(last_id, model_column_id)
            matched += 1

            reasons = [
                "backfill_from_model_column_semantic_concept_map",
                f"relationship_kind:{str(row.get('relationship_kind') or '').strip().lower()}",
                f"vertical_norm:{str(row.get('vertical_norm') or '').strip().lower()}",
            ]
            confidence = _clamp_confidence(row.get("weight"))
            updates.append(
                {
                    "model_column_id": model_column_id,
                    "semantic_concept_id": int(row["semantic_concept_id"]),
                    "semantic_concept_key": str(row.get("concept_key") or "").strip().upper() or None,
                    "semantic_entity": _as_nullable_text(row.get("entity"), max_len=100),
                    "semantic_sub_type": _as_nullable_text(row.get("sub_type"), max_len=200),
                    "semantic_granularity_rank": int(row.get("granularity_rank") or 0),
                    "semantic_source": source_value,
                    "semantic_confidence": confidence,
                    "semantic_reasons_json": json.dumps(reasons),
                    "semantic_warnings_json": json.dumps([]),
                }
            )

        if dry_run:
            logger.info(
                "Dry-run batch: rows=%s last_model_column_id=%s",
                len(updates),
                last_id,
            )
            continue

        with sql.transaction() as tx:
            for payload in updates:
                tx.execute_write(
                    """
                    UPDATE model_column
                    SET semantic_concept_id = :semantic_concept_id,
                        semantic_concept_key = :semantic_concept_key,
                        semantic_entity = :semantic_entity,
                        semantic_sub_type = :semantic_sub_type,
                        semantic_granularity_rank = :semantic_granularity_rank,
                        semantic_source = :semantic_source,
                        semantic_confidence = :semantic_confidence,
                        semantic_reasons_json = :semantic_reasons_json,
                        semantic_warnings_json = :semantic_warnings_json,
                        semantic_updated_at = CURRENT_TIMESTAMP
                    WHERE id = :model_column_id
                    """,
                    payload,
                )
        updated += len(updates)
        logger.info("Backfill batch updated=%s last_model_column_id=%s", len(updates), last_id)

    result = {
        "vertical_norm": vertical,
        "batch_size": int(batch_size),
        "dry_run": bool(dry_run),
        "force": bool(force),
        "source": source_value,
        "scanned": scanned,
        "matched": matched,
        "updated": updated,
    }
    logger.info("Backfill model_column semantics complete: %s", result)
    return result


def _load_best_rows(
    *,
    sql: MySQLSQLExecutor,
    last_id: int,
    limit: int,
    vertical_norm: Optional[str],
    force: bool,
) -> List[Dict[str, Any]]:
    return sql.execute_query_mappings(
        """
        WITH ranked AS (
          SELECT
            m.model_column_id,
            m.vertical_norm,
            m.relationship_kind,
            m.weight,
            m.semantic_concept_id,
            sc.concept_key,
            sc.entity,
            sc.sub_type,
            sc.granularity_rank,
            ROW_NUMBER() OVER (
              PARTITION BY m.model_column_id
              ORDER BY
                CASE
                  WHEN :vertical_norm IS NOT NULL AND m.vertical_norm = :vertical_norm THEN 0
                  WHEN m.vertical_norm = 'generic' THEN 2
                  ELSE 1
                END,
                CASE WHEN m.relationship_kind = 'primary' THEN 0 ELSE 1 END,
                m.weight DESC,
                m.semantic_concept_id ASC
            ) AS rn
          FROM model_column_semantic_concept_map m
          JOIN semantic_concept sc
            ON sc.id = m.semantic_concept_id
          JOIN model_column mc
            ON mc.id = m.model_column_id
          WHERE m.model_column_id > :last_id
            AND (:vertical_norm IS NULL OR m.vertical_norm IN (:vertical_norm, 'generic'))
            AND (
              :force = 1
              OR mc.semantic_concept_id IS NULL
              OR mc.semantic_concept_key IS NULL
              OR mc.semantic_concept_key = ''
            )
        )
        SELECT
          model_column_id,
          vertical_norm,
          relationship_kind,
          weight,
          semantic_concept_id,
          concept_key,
          entity,
          sub_type,
          granularity_rank
        FROM ranked
        WHERE rn = 1
        ORDER BY model_column_id
        LIMIT :limit
        """,
        {
            "last_id": int(last_id),
            "limit": int(limit),
            "vertical_norm": vertical_norm,
            "force": 1 if force else 0,
        },
    )


def _normalize_vertical(vertical_norm: Optional[str]) -> Optional[str]:
    if vertical_norm is None:
        return None
    text = str(vertical_norm).strip().lower()
    return text or None


def _as_nullable_text(value: Any, *, max_len: int) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    if text == "":
        return None
    if len(text) > max_len:
        return text[:max_len]
    return text


def _clamp_confidence(value: Any) -> float:
    try:
        parsed = float(value)
    except Exception:
        parsed = 0.0
    return max(0.0, min(1.0, parsed))


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Backfill model_column semantic assignment fields from concept map.")
    parser.add_argument("--vertical-norm", dest="vertical_norm", default=None, help="Optional vertical scope (e.g. education).")
    parser.add_argument("--batch-size", dest="batch_size", type=int, default=DEFAULT_BATCH_SIZE, help="Rows per batch.")
    parser.add_argument("--dry-run", dest="dry_run", action="store_true", help="Compute updates without writing.")
    parser.add_argument(
        "--force",
        dest="force",
        action="store_true",
        help="Overwrite existing semantic_* assignments (default only fills empty).",
    )
    parser.add_argument(
        "--source",
        dest="source",
        default=DEFAULT_SOURCE,
        help="semantic_source value to write (default: manual).",
    )
    return parser


def main() -> None:
    parser = _build_arg_parser()
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s - %(message)s")
    result = backfill_model_column_semantics(
        vertical_norm=args.vertical_norm,
        batch_size=max(1, int(args.batch_size or DEFAULT_BATCH_SIZE)),
        dry_run=bool(args.dry_run),
        force=bool(args.force),
        source=str(args.source or DEFAULT_SOURCE),
    )
    logger.info("Result: %s", result)


if __name__ == "__main__":
    main()
