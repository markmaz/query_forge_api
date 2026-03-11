from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime
from typing import Any, Dict, Iterable, List, Mapping, Optional

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.exceptions.forge_error import ForgeError
from app.ports.sql_executor import ForgeQueryPort
from app.services.semantic.catalog.catalog_models import ColumnProfile

logger = logging.getLogger(__name__)

_NUMERIC_TYPE_RE = re.compile(r"\b(int|bigint|smallint|tinyint|decimal|number|numeric|double|float|real)\b", re.IGNORECASE)
_DATE_TYPE_RE = re.compile(r"\b(date|datetime|timestamp|time)\b", re.IGNORECASE)
_IDENTIFIER_NAME_RE = re.compile(r"(^id$|_id$|^k_|_key$|uuid$|guid$|identifier$)", re.IGNORECASE)
_NUMERIC_VALUE_RE = re.compile(r"^-?\d+(\.\d+)?$")


class ColumnProfileBuilder:
    """
    Stage 1: build normalized column profiles from workspace metadata + sampled stats.

    This is intentionally deterministic and cheap so that LLM enrichment only receives
    pre-filtered, high-signal column cards.
    """

    def __init__(self, *, sql: Optional[ForgeQueryPort] = None) -> None:
        self._sql = sql or ForgeMetaSQL()

    def build_profiles(
        self,
        *,
        workspace_id: str,
        domain_id: Optional[int] = None,
        workspace_table_ids: Optional[Iterable[int]] = None,
        only_exists_in_source: bool = True,
        limit: int = 5000,
        offset: int = 0,
    ) -> List[ColumnProfile]:
        ws = str(workspace_id or "").strip()
        if ws == "":
            raise ForgeError("workspace_id is required", status_code=400)

        params: Dict[str, Any] = {
            "workspace_id": ws,
            "domain_id": int(domain_id) if domain_id is not None else None,
            "limit": max(1, int(limit)),
            "offset": max(0, int(offset)),
            "only_exists": 1 if only_exists_in_source else 0,
        }

        where_parts = [
            "wt.workspace_id = :workspace_id",
            "(:domain_id IS NULL OR dwt.domain_id = :domain_id)",
            "(:only_exists = 0 OR wt.exists_in_dbx = 1)",
            "(:only_exists = 0 OR wc.exists_in_dbx = 1)",
            "(:only_exists = 0 OR wc.is_missing_in_source = 0 OR wc.is_missing_in_source IS NULL)",
        ]

        table_ids = [int(x) for x in (workspace_table_ids or [])]
        if table_ids:
            placeholders: List[str] = []
            for idx, table_id in enumerate(table_ids):
                key = f"wtid_{idx}"
                params[key] = table_id
                placeholders.append(f":{key}")
            where_parts.append(f"wt.id IN ({', '.join(placeholders)})")

        rows = self._sql.execute_query_mappings(
            f"""
            SELECT
              wt.id AS workspace_table_id,
              wc.id AS workspace_column_id,
              COALESCE(NULLIF(wt.source_table_name, ''), wt.table_name, wt.full_name) AS table_name,
              wc.column_name,
              wc.data_type,
              wc.nullable,
              wc.sample_values_json,
              wc.sample_stats_json
            FROM workspace_table wt
            JOIN workspace_column wc
              ON wc.workspace_table_id = wt.id
            LEFT JOIN domain_workspace_table dwt
              ON dwt.workspace_table_id = wt.id
            WHERE {' AND '.join(where_parts)}
            ORDER BY wt.id ASC, wc.id ASC
            LIMIT :limit OFFSET :offset
            """,
            params,
        )

        profiles: List[ColumnProfile] = []
        for row in rows:
            stats = _parse_json_obj(row.get("sample_stats_json"))
            sample_values = _parse_json_list(row.get("sample_values_json"))
            data_type = str(row.get("data_type") or "").strip()
            row_count = _to_int_first(stats, keys=("row_count", "total_rows", "sample_row_count"))
            distinct_count = _to_int_first(stats, keys=("distinct_count", "approx_distinct", "approx_distinct_count"))
            min_value = _first_present(stats, ("min_value", "min"))
            max_value = _first_present(stats, ("max_value", "max"))

            numeric_flag = _infer_is_numeric(data_type=data_type, sample_values=sample_values)
            date_flag = _infer_is_date_like(data_type=data_type, sample_values=sample_values)
            identifier_flag = _infer_is_identifier(
                column_name=str(row.get("column_name") or ""),
                distinct_count=distinct_count,
                row_count=row_count,
            )
            enum_flag = _infer_is_enum_like(
                distinct_count=distinct_count,
                row_count=row_count,
                sample_values=sample_values,
                is_numeric=numeric_flag,
                is_date_like=date_flag,
            )
            measure_flag = bool(numeric_flag and not identifier_flag and not date_flag)
            dimension_flag = bool(not measure_flag and (enum_flag or date_flag or not numeric_flag or identifier_flag))

            profile = ColumnProfile(
                workspace_table_id=int(row.get("workspace_table_id") or 0),
                workspace_column_id=int(row.get("workspace_column_id") or 0),
                table_name=str(row.get("table_name") or "").strip(),
                column_name=str(row.get("column_name") or "").strip(),
                data_type=data_type,
                nullable=bool(row.get("nullable") in (1, True, "1", "true", "TRUE", "yes", "YES")),
                distinct_count=distinct_count,
                row_count=row_count,
                sample_values=sample_values,
                min_value=min_value,
                max_value=max_value,
                is_identifier=identifier_flag,
                is_numeric=numeric_flag,
                is_date_like=date_flag,
                is_enum_like=enum_flag,
                is_dimension_candidate=dimension_flag,
                is_measure_candidate=measure_flag,
            )
            profiles.append(profile)

        logger.info(
            "semantic_catalog column_profile_builder workspace_id=%s domain_id=%s profiles=%s",
            ws,
            str(domain_id) if domain_id is not None else "*",
            len(profiles),
        )
        return profiles


def _parse_json_obj(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        text = value.strip()
        if text == "":
            return {}
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                return dict(parsed)
        except Exception:
            return {}
    return {}


def _parse_json_list(value: Any) -> List[Any]:
    if isinstance(value, list):
        return list(value)[:25]
    if isinstance(value, str):
        text = value.strip()
        if text == "":
            return []
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                return list(parsed)[:25]
        except Exception:
            return []
    return []


def _first_present(data: Mapping[str, Any], keys: Iterable[str]) -> Optional[Any]:
    for key in keys:
        if key in data and data.get(key) is not None:
            return data.get(key)
    return None


def _to_int_first(data: Mapping[str, Any], *, keys: Iterable[str]) -> Optional[int]:
    raw = _first_present(data, keys)
    if raw is None:
        return None
    try:
        return int(raw)
    except Exception:
        return None


def _infer_is_numeric(*, data_type: str, sample_values: List[Any]) -> bool:
    if _NUMERIC_TYPE_RE.search(str(data_type or "")) is not None:
        return True
    text_values = [str(v).strip() for v in sample_values if v is not None and str(v).strip() != ""]
    if not text_values:
        return False
    numeric_hits = sum(1 for token in text_values if _NUMERIC_VALUE_RE.match(token))
    return numeric_hits >= max(1, int(len(text_values) * 0.8))


def _infer_is_date_like(*, data_type: str, sample_values: List[Any]) -> bool:
    if _DATE_TYPE_RE.search(str(data_type or "")) is not None:
        return True
    text_values = [str(v).strip() for v in sample_values if v is not None and str(v).strip() != ""]
    if not text_values:
        return False
    hits = sum(1 for token in text_values if _looks_like_date(token))
    return hits >= max(1, int(len(text_values) * 0.7))


def _infer_is_identifier(*, column_name: str, distinct_count: Optional[int], row_count: Optional[int]) -> bool:
    name = str(column_name or "").strip().lower()
    if _IDENTIFIER_NAME_RE.search(name):
        return True
    if distinct_count is None or row_count in (None, 0):
        return False
    ratio = float(distinct_count) / float(row_count)
    return ratio >= 0.95


def _infer_is_enum_like(
    *,
    distinct_count: Optional[int],
    row_count: Optional[int],
    sample_values: List[Any],
    is_numeric: bool,
    is_date_like: bool,
) -> bool:
    if is_numeric or is_date_like:
        return False
    if distinct_count is not None and distinct_count <= 50:
        if row_count in (None, 0):
            return True
        ratio = float(distinct_count) / float(row_count)
        if ratio <= 0.25:
            return True
    text_values = [str(v).strip() for v in sample_values if v is not None and str(v).strip() != ""]
    if not text_values:
        return False
    short_values = [v for v in text_values if len(v) <= 40]
    return len(short_values) >= max(1, int(len(text_values) * 0.8))


def _looks_like_date(value: str) -> bool:
    token = str(value or "").strip()
    if token == "":
        return False
    for parser in (
        datetime.fromisoformat,
        date.fromisoformat,
    ):
        try:
            parser(token.replace("Z", "+00:00"))
            return True
        except Exception:
            pass
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y/%m/%d", "%Y%m%d"):
        try:
            datetime.strptime(token, fmt)
            return True
        except Exception:
            continue
    return False
