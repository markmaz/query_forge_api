from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Mapping, Optional, Sequence

from app.adapters.mysql_sql_executor import MySQLSQLExecutor
from app.exceptions.service_error import ServiceError
from app.ports.sql_executor import SQLExecutor

logger = logging.getLogger(__name__)

_NAME_TOKEN_RE = re.compile(r"[^a-z0-9]+")

_OVERLAY_CATALOG: List[Dict[str, Any]] = [
    {
        "overlay_key": "students_per_teacher",
        "label": "Students per Teacher",
        "vertical_norm": "education",
        "base_domain_name_tokens": ["enrollment", "student"],
        "requires_domain_name_tokens": ["staff"],
    }
]


class DomainCapabilitiesService:
    def __init__(self, *, sql: Optional[SQLExecutor] = None) -> None:
        self._sql = sql or MySQLSQLExecutor()

    def get_domain_capabilities(
        self,
        *,
        workspace_id: str,
        user_id: str,
        domain_id: int,
        vertical_norm: str = "generic",
    ) -> Dict[str, Any]:
        domain = self._load_domain(workspace_id=workspace_id, user_id=user_id, domain_id=domain_id)
        columns = self._load_domain_columns(workspace_id=workspace_id, domain_id=domain_id)
        dimensions = self._build_dimension_rows(columns)
        time_columns = [row for row in dimensions if bool(row.get("is_time"))]
        domain_metrics = self._build_domain_metrics(domain.get("metrics"))
        overlay_metrics = self._build_overlay_metrics(
            workspace_id=workspace_id,
            base_domain_id=domain_id,
            base_domain_name=str(domain.get("name") or ""),
            vertical_norm=vertical_norm,
        )

        return {
            "domain_id": int(domain_id),
            "domain_version": _to_int(domain.get("domain_version")) or 0,
            "dimensions": [self._strip_internal_fields(row) for row in dimensions],
            "domain_metrics": domain_metrics,
            "user_metrics": [],
            "overlay_metrics": overlay_metrics,
            "time_columns": [self._strip_internal_fields(row) for row in time_columns],
        }

    def get_overlay_metrics(
        self,
        *,
        workspace_id: str,
        user_id: str,
        domain_id: int,
        vertical_norm: str = "generic",
    ) -> List[Dict[str, Any]]:
        domain = self._load_domain(workspace_id=workspace_id, user_id=user_id, domain_id=domain_id)
        return self._build_overlay_metrics(
            workspace_id=workspace_id,
            base_domain_id=domain_id,
            base_domain_name=str(domain.get("name") or ""),
            vertical_norm=vertical_norm,
        )

    def _load_domain(self, *, workspace_id: str, user_id: str, domain_id: int) -> Dict[str, Any]:
        params: Dict[str, Any] = {
            "workspace_id": str(workspace_id),
            "user_id": str(user_id),
            "domain_id": int(domain_id),
        }
        rows = self._sql.execute_query_mappings(
            """
            SELECT
              d.id AS domain_id,
              d.name,
              d.kind,
              d.description,
              dp.metrics,
              COALESCE(UNIX_TIMESTAMP(dp.updated_at), UNIX_TIMESTAMP(dp.created_at), 0) AS domain_version
            FROM domain d
            LEFT JOIN domain_profile dp
              ON dp.domain_id = d.id
             AND dp.workspace_id = d.workspace_id
            WHERE d.workspace_id = :workspace_id
              AND d.id = :domain_id
              AND d.is_active = 1
              AND EXISTS (
                SELECT 1
                FROM user_domain_mapping udm
                WHERE udm.domain_id = d.id
                  AND udm.user_id = :user_id
                  AND udm.can_read = 1
              )
            LIMIT 1
            """,
            params,
        )
        if not rows:
            raise ServiceError("Domain not found or access denied", status_code=404)
        return dict(rows[0])

    def _load_domain_columns(self, *, workspace_id: str, domain_id: int) -> List[Dict[str, Any]]:
        rows = self._sql.execute_query_mappings(
            """
            SELECT
              wt.id AS workspace_table_id,
              wt.table_name,
              wc.column_name,
              wc.data_type,
              wc.nullable,
              mc.id AS model_column_id,
              mc.semantic_type,
              mc.description
            FROM domain_workspace_table dwt
            JOIN workspace_table wt
              ON wt.id = dwt.workspace_table_id
             AND wt.workspace_id = :workspace_id
             AND wt.exists_in_dbx = 1
            JOIN workspace_column wc
              ON wc.workspace_table_id = wt.id
            LEFT JOIN model_column mc
              ON mc.model_table_id = wt.model_table_id
             AND mc.column_name = wc.column_name
             AND mc.is_active = 1
             AND mc.is_missing_in_source = 0
            WHERE dwt.domain_id = :domain_id
            ORDER BY wt.id ASC, wc.ordinal_position ASC
            """,
            {"workspace_id": str(workspace_id), "domain_id": int(domain_id)},
        )
        return [dict(row) for row in rows]

    def _build_dimension_rows(self, rows: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        seen: set[str] = set()
        for row in rows:
            workspace_table_id = _to_int(row.get("workspace_table_id"))
            column_name = str(row.get("column_name") or "").strip()
            if workspace_table_id is None or column_name == "":
                continue
            key = f"wt{workspace_table_id}.{column_name.lower()}"
            if key in seen:
                continue
            seen.add(key)
            data_type = str(row.get("data_type") or "").strip().lower()
            semantic_type = str(row.get("semantic_type") or "").strip().lower()
            is_time = _looks_like_time_column(column_name=column_name, data_type=data_type, semantic_type=semantic_type)
            out.append(
                {
                    "column_key": key,
                    "label": _column_label(column_name=column_name, description=row.get("description")),
                    "data_type": data_type or "unknown",
                    "filterable": data_type not in {"array", "map", "struct", "json"},
                    "workspace_table_id": workspace_table_id,
                    "model_column_id": _to_int(row.get("model_column_id")),
                    "column_name": column_name,
                    "table_name": str(row.get("table_name") or ""),
                    "semantic_type": semantic_type or "unknown",
                    "is_time": is_time,
                }
            )
        return out

    def _build_domain_metrics(self, raw_metrics: Any) -> List[Dict[str, Any]]:
        metric_entries = _parse_json_list(raw_metrics)
        out: List[Dict[str, Any]] = []
        seen: set[str] = set()
        for item in metric_entries:
            if isinstance(item, str):
                key = _to_metric_key(item)
                if key == "" or key in seen:
                    continue
                seen.add(key)
                out.append(
                    {
                        "metric_key": key,
                        "label": _metric_label(item),
                        "kind": _infer_metric_kind(key),
                        "agg": _default_metric_agg(key),
                    }
                )
                continue
            if isinstance(item, Mapping):
                key = _to_metric_key(item.get("metric_key") or item.get("key") or item.get("name"))
                if key == "" or key in seen:
                    continue
                seen.add(key)
                out.append(
                    {
                        "metric_key": key,
                        "label": str(item.get("label") or _metric_label(key)),
                        "kind": str(item.get("kind") or _infer_metric_kind(key)).strip().lower(),
                        "agg": str(item.get("agg") or _default_metric_agg(key)).strip().lower(),
                        "column_key": str(item.get("column_key") or "").strip().lower() or None,
                        "sql_metric": dict(item.get("sql_metric") or {}) if isinstance(item.get("sql_metric"), Mapping) else None,
                    }
                )
        return out

    def _build_overlay_metrics(
        self,
        *,
        workspace_id: str,
        base_domain_id: int,
        base_domain_name: str,
        vertical_norm: str,
    ) -> List[Dict[str, Any]]:
        overlays: List[Dict[str, Any]] = []
        domain_name_norm = _norm_token_blob(base_domain_name)
        related_domains = self._load_workspace_domain_name_map(workspace_id=workspace_id)
        for item in _OVERLAY_CATALOG:
            overlay_vertical = str(item.get("vertical_norm") or "generic").strip().lower()
            if overlay_vertical != str(vertical_norm or "generic").strip().lower():
                continue
            required_tokens = [str(token).strip().lower() for token in list(item.get("base_domain_name_tokens") or [])]
            if required_tokens and not any(token in domain_name_norm for token in required_tokens):
                continue
            requires = [int(base_domain_id)]
            extra_domain_id = _find_domain_by_tokens(
                domain_name_map=related_domains,
                tokens=list(item.get("requires_domain_name_tokens") or []),
                exclude_domain_id=int(base_domain_id),
            )
            if extra_domain_id is not None:
                requires.append(extra_domain_id)
            overlays.append(
                {
                    "overlay_key": str(item.get("overlay_key") or "").strip().lower(),
                    "label": str(item.get("label") or "").strip(),
                    "requires": requires,
                }
            )
        return overlays

    def _load_workspace_domain_name_map(self, *, workspace_id: str) -> Dict[int, str]:
        rows = self._sql.execute_query_mappings(
            """
            SELECT id, name
            FROM domain
            WHERE workspace_id = :workspace_id
              AND is_active = 1
            ORDER BY id ASC
            """,
            {"workspace_id": str(workspace_id)},
        )
        return {int(row["id"]): str(row.get("name") or "") for row in rows if _to_int(row.get("id")) is not None}

    @staticmethod
    def _strip_internal_fields(row: Mapping[str, Any]) -> Dict[str, Any]:
        out = dict(row)
        out.pop("is_time", None)
        return out


def _find_domain_by_tokens(
    *,
    domain_name_map: Mapping[int, str],
    tokens: Sequence[str],
    exclude_domain_id: int,
) -> Optional[int]:
    norm_tokens = [str(token).strip().lower() for token in tokens if str(token).strip()]
    if not norm_tokens:
        return None
    for domain_id, domain_name in domain_name_map.items():
        if int(domain_id) == int(exclude_domain_id):
            continue
        blob = _norm_token_blob(domain_name)
        if any(token in blob for token in norm_tokens):
            return int(domain_id)
    return None


def _norm_token_blob(text: Any) -> str:
    return " ".join(_NAME_TOKEN_RE.sub(" ", str(text or "").strip().lower()).split())


def _parse_json_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return list(value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        value = bytes(value).decode("utf-8", errors="ignore")
    text = str(value or "").strip()
    if text == "":
        return []
    try:
        parsed = json.loads(text)
    except Exception:
        return []
    return parsed if isinstance(parsed, list) else []


def _to_metric_key(value: Any) -> str:
    text = _norm_token_blob(value)
    return "_".join(text.split())


def _metric_label(value: Any) -> str:
    text = str(value or "").replace("_", " ").strip()
    return " ".join(word.capitalize() for word in text.split())


def _infer_metric_kind(metric_key: str) -> str:
    key = str(metric_key or "").strip().lower()
    if "ratio" in key or "rate" in key or "_per_" in key:
        return "ratio"
    if "count" in key or "total" in key:
        return "count"
    return "numeric"


def _default_metric_agg(metric_key: str) -> str:
    kind = _infer_metric_kind(metric_key)
    if kind == "count":
        return "count"
    if kind == "ratio":
        return "count_distinct"
    return "sum"


def _column_label(*, column_name: str, description: Any) -> str:
    desc = str(description or "").strip()
    if desc:
        return desc
    text = str(column_name or "").replace("_", " ").strip()
    return " ".join(word.capitalize() for word in text.split())


def _looks_like_time_column(*, column_name: str, data_type: str, semantic_type: str) -> bool:
    name = str(column_name or "").strip().lower()
    dtype = str(data_type or "").strip().lower()
    sem = str(semantic_type or "").strip().lower()
    if sem in {"time", "date", "datetime"}:
        return True
    if any(token in dtype for token in ("date", "time", "timestamp")):
        return True
    return any(token in name for token in ("date", "year", "month", "week", "semester", "term"))


def _to_int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except Exception:
        return None


__all__ = ["DomainCapabilitiesService"]
