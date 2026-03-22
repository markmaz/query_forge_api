from __future__ import annotations

import json
import re
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.config import SEMANTIC_SAMPLE_VALUES_LIMIT, SEMANTIC_STATS_ENABLED
from app.ports.sql_executor import ForgeQueryPort

_YEAR_RE = re.compile(r"^\d{4}$")
_NUMERIC_RE = re.compile(r"^-?\d+(\.\d+)?$")


class SemanticCardService:
    def __init__(
        self,
        *,
        sql: Optional[ForgeQueryPort] = None,
        sample_values_limit: Optional[int] = None,
        stats_enabled: Optional[bool] = None,
        metadata_mode: Optional[str] = None,
    ) -> None:
        del metadata_mode
        self._sql = sql or ForgeMetaSQL()
        self._sample_values_limit = max(1, int(sample_values_limit or SEMANTIC_SAMPLE_VALUES_LIMIT))
        self._stats_enabled = SEMANTIC_STATS_ENABLED if stats_enabled is None else bool(stats_enabled)

    def count_columns(
        self,
        *,
        model_table_id: Optional[int] = None,
        workspace_table_id: Optional[int] = None,
    ) -> int:
        return self._count_columns_workspace(
            legacy_table_id=model_table_id,
            workspace_table_id=workspace_table_id,
        )

    def _count_columns_workspace(
        self,
        *,
        legacy_table_id: Optional[int],
        workspace_table_id: Optional[int],
    ) -> int:
        params: Dict[str, Any] = {}
        where_parts = ["wt.exists_in_dbx = 1", "wc.exists_in_dbx = 1"]
        if workspace_table_id is not None:
            where_parts.append("wc.workspace_table_id = :workspace_table_id")
            params["workspace_table_id"] = int(workspace_table_id)
        if legacy_table_id is not None:
            # Legacy compatibility: treat the old table id input as workspace_table_id.
            where_parts.append("wc.workspace_table_id = :legacy_table_id")
            params["legacy_table_id"] = int(legacy_table_id)

        where_sql = f"WHERE {' AND '.join(where_parts)}"
        rows = self._sql.execute_query_mappings(
            f"""
            SELECT COUNT(*) AS total
            FROM workspace_column wc
            JOIN workspace_table wt
              ON wt.id = wc.workspace_table_id
            {where_sql}
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
        workspace_table_id: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        return self._build_column_cards_workspace(
            offset=offset,
            limit=limit,
            legacy_table_id=model_table_id,
            workspace_table_id=workspace_table_id,
        )

    def _build_column_cards_workspace(
        self,
        *,
        offset: int,
        limit: int,
        legacy_table_id: Optional[int],
        workspace_table_id: Optional[int],
    ) -> List[Dict[str, Any]]:
        params: Dict[str, Any] = {"offset": max(0, int(offset)), "limit": max(1, int(limit))}
        where_parts = ["wt.exists_in_dbx = 1", "wc.exists_in_dbx = 1"]
        if legacy_table_id is not None:
            # Legacy compatibility: treat the old table id input as workspace_table_id.
            where_parts.append("wc.workspace_table_id = :legacy_table_id")
            params["legacy_table_id"] = int(legacy_table_id)
        if workspace_table_id is not None:
            where_parts.append("wc.workspace_table_id = :workspace_table_id")
            params["workspace_table_id"] = int(workspace_table_id)
        where_sql = f"WHERE {' AND '.join(where_parts)}"

        rows = self._sql.execute_query_mappings(
            f"""
            SELECT
              wc.id AS workspace_column_id,
              wt.id AS workspace_table_id,
              COALESCE(NULLIF(wt.source_table_name, ''), wt.table_name, wt.full_name) AS table_name,
              wc.column_name,
              wc.data_type,
              wc.description,
              wc.sample_values_json,
              wc.sample_stats_json
            FROM workspace_column wc
            JOIN workspace_table wt
              ON wt.id = wc.workspace_table_id
            {where_sql}
            ORDER BY wc.id
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
                    "modelColumnId": int(row["workspace_column_id"]),
                    "modelTableId": int(row["workspace_table_id"]),
                    "workspaceColumnId": int(row["workspace_column_id"]),
                    "workspaceTableId": int(row["workspace_table_id"]),
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
