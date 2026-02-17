from __future__ import annotations

import json
import re
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from app.adapters.mysql_sql_executor import MySQLSQLExecutor
from app.config import SEMANTIC_SAMPLE_VALUES_LIMIT, SEMANTIC_STATS_ENABLED
from app.ports.sql_executor import SQLExecutor

_YEAR_RE = re.compile(r"^\d{4}$")
_NUMERIC_RE = re.compile(r"^-?\d+(\.\d+)?$")


class SemanticCardService:
    def __init__(
        self,
        *,
        sql: Optional[SQLExecutor] = None,
        sample_values_limit: Optional[int] = None,
        stats_enabled: Optional[bool] = None,
    ) -> None:
        self._sql = sql or MySQLSQLExecutor()
        self._sample_values_limit = max(1, int(sample_values_limit or SEMANTIC_SAMPLE_VALUES_LIMIT))
        self._stats_enabled = SEMANTIC_STATS_ENABLED if stats_enabled is None else bool(stats_enabled)

    def count_columns(self, *, model_table_id: Optional[int] = None) -> int:
        params: Dict[str, Any] = {}
        where = ""
        if model_table_id is not None:
            where = "WHERE mc.model_table_id = :model_table_id"
            params["model_table_id"] = int(model_table_id)

        rows = self._sql.execute_query_mappings(
            f"""
            SELECT COUNT(*) AS total
            FROM model_column mc
            {where}
            """,
            params,
        )
        return int((rows[0] or {}).get("total") or 0) if rows else 0

    def build_column_cards(
        self,
        *,
        offset: int,
        limit: int,
        model_table_id: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        params: Dict[str, Any] = {"offset": max(0, int(offset)), "limit": max(1, int(limit))}
        where_parts = []
        if model_table_id is not None:
            where_parts.append("mc.model_table_id = :model_table_id")
            params["model_table_id"] = int(model_table_id)

        where_sql = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""
        rows = self._sql.execute_query_mappings(
            f"""
            SELECT
              mc.id AS model_column_id,
              mc.model_table_id,
              mt.name AS table_name,
              mc.column_name,
              mc.data_type,
              mc.description,
              mc.sample_values_json,
              mc.sample_stats_json
            FROM model_column mc
            LEFT JOIN model_table mt ON mt.id = mc.model_table_id
            {where_sql}
            ORDER BY mc.id
            LIMIT :limit OFFSET :offset
            """,
            params,
        )

        cards: List[Dict[str, Any]] = []
        for row in rows:
            samples = _parse_samples(row.get("sample_values_json"), self._sample_values_limit)
            stats = _parse_json_obj(row.get("sample_stats_json")) if self._stats_enabled else None
            signals = _derive_signals(samples, stats)
            cards.append(
                {
                    "modelColumnId": int(row["model_column_id"]),
                    "modelTableId": int(row["model_table_id"]) if row.get("model_table_id") is not None else None,
                    "tableName": row.get("table_name"),
                    "columnName": row.get("column_name"),
                    "dataType": row.get("data_type"),
                    "description": row.get("description"),
                    "samples": samples,
                    "signals": signals,
                }
            )
        return cards


def _parse_samples(value: Any, limit: int) -> List[Any]:
    parsed = _parse_json_any(value)
    if isinstance(parsed, list):
        return parsed[:limit]
    return []


def _parse_json_obj(value: Any) -> Optional[Dict[str, Any]]:
    parsed = _parse_json_any(value)
    if isinstance(parsed, dict):
        return parsed
    return None


def _parse_json_any(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (list, dict)):
        return value
    if isinstance(value, str):
        text = value.strip()
        if text == "":
            return None
        try:
            return json.loads(text)
        except Exception:
            return None
    return None


def _derive_signals(samples: List[Any], stats: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    texts = [str(v).strip() for v in samples if v is not None and str(v).strip() != ""]
    normalized = [t.lower() for t in texts]

    all_numeric = bool(texts) and all(_is_numeric(t) for t in texts)
    boolean_like = bool(texts) and all(t in {"true", "false", "1", "0", "y", "n", "yes", "no"} for t in normalized)
    date_like = bool(texts) and all(_is_year_or_date(t) for t in texts)
    contains_county_word = any("county" in t for t in normalized)

    unique_ratio_estimate = None
    if stats:
        for key in ("unique_ratio_estimate", "unique_ratio", "distinct_ratio"):
            if key in stats and stats[key] is not None:
                try:
                    unique_ratio_estimate = float(stats[key])
                except Exception:
                    unique_ratio_estimate = None
                break

    return {
        "all_numeric": all_numeric,
        "boolean_like": boolean_like,
        "date_like": date_like,
        "contains_county_word": contains_county_word,
        "unique_ratio_estimate": unique_ratio_estimate,
    }


def _is_numeric(value: str) -> bool:
    return bool(_NUMERIC_RE.match(value))


def _is_year_or_date(value: str) -> bool:
    if _YEAR_RE.match(value):
        return True
    try:
        if value.endswith("Z"):
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        else:
            datetime.fromisoformat(value)
        return True
    except Exception:
        pass

    for fmt in ("%Y-%m-%d", "%m/%d/%Y"):
        try:
            datetime.strptime(value, fmt)
            return True
        except Exception:
            continue

    try:
        date.fromisoformat(value)
        return True
    except Exception:
        return False
