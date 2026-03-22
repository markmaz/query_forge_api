from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, Optional

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.exceptions.forge_error import ForgeError
from app.ports.sql_executor import ForgeQueryPort

ALLOWED_SEMANTIC_TYPES = {
    "entity",
    "identifier",
    "attribute",
    "geography",
    "time",
    "metric",
    "flag",
    "reference",
    "other",
}

BOOL_FIELDS = {
    "filter_allowed",
    "group_by_allowed",
    "aggregation_allowed",
    "is_identifier",
    "is_metric",
    "sensitive",
}
INT_FIELDS = {"granularity_rank", "display_priority"}
WRITEABLE_FIELDS = {
    "vertical",
    "concept_key",
    "semantic_type",
    "sub_type",
    "entity",
    "description",
    "granularity_rank",
    "filter_allowed",
    "group_by_allowed",
    "aggregation_allowed",
    "is_identifier",
    "is_metric",
    "display_priority",
    "sensitive",
}


class SemanticRegistryService:
    def __init__(self, *, sql: Optional[ForgeQueryPort] = None) -> None:
        self._sql = sql or ForgeMetaSQL()

    def list_entries(
        self,
        *,
        vertical: Optional[str] = None,
        q: Optional[str] = None,
        semantic_type: Optional[str] = None,
        entity: Optional[str] = None,
        page: int = 1,
        page_size: int = 25,
    ) -> Dict[str, Any]:
        page_val = max(1, int(page or 1))
        size_val = min(200, max(1, int(page_size or 25)))
        offset = (page_val - 1) * size_val

        where = []
        params: Dict[str, Any] = {"limit": size_val, "offset": offset}

        vertical_norm = _normalize_vertical(vertical)
        if vertical_norm is not None:
            where.append("sr.vertical_norm = :vertical_norm")
            params["vertical_norm"] = vertical_norm

        if semantic_type is not None and str(semantic_type).strip() != "":
            st = str(semantic_type).strip().lower()
            self._validate_semantic_type(st)
            where.append("sr.semantic_type = :semantic_type")
            params["semantic_type"] = st

        if entity is not None and str(entity).strip() != "":
            where.append("LOWER(COALESCE(sr.entity, '')) = :entity")
            params["entity"] = str(entity).strip().lower()

        if q is not None and str(q).strip() != "":
            where.append("(LOWER(sr.concept_key) LIKE :q OR LOWER(COALESCE(sr.description, '')) LIKE :q)")
            params["q"] = f"%{str(q).strip().lower()}%"

        where_sql = f"WHERE {' AND '.join(where)}" if where else ""

        rows = self._sql.execute_query_mappings(
            f"""
            SELECT
              sr.id,
              sr.vertical,
              sr.vertical_norm,
              sr.concept_key,
              sr.semantic_type,
              sr.sub_type,
              sr.entity,
              sr.description,
              sr.granularity_rank,
              sr.filter_allowed,
              sr.group_by_allowed,
              sr.aggregation_allowed,
              sr.is_identifier,
              sr.is_metric,
              sr.display_priority,
              sr.`sensitive` AS `sensitive`,
              sr.created_at,
              sr.updated_at
            FROM semantic_registry sr
            {where_sql}
            ORDER BY sr.display_priority DESC, sr.granularity_rank ASC, sr.concept_key ASC
            LIMIT :limit OFFSET :offset
            """,
            params,
        )

        total_rows = self._sql.execute_query_mappings(
            f"""
            SELECT COUNT(*) AS total
            FROM semantic_registry sr
            {where_sql}
            """,
            {k: v for k, v in params.items() if k not in {"limit", "offset"}},
        )
        total = int((total_rows[0] or {}).get("total") or 0) if total_rows else 0

        return {
            "rows": [self._normalize_row(row) for row in rows],
            "total": total,
            "page": page_val,
            "page_size": size_val,
        }

    def get_entry(self, entry_id: int) -> Dict[str, Any]:
        row_id = _coerce_positive_int(entry_id, field="id")
        rows = self._sql.execute_query_mappings(
            """
            SELECT
              sr.id,
              sr.vertical,
              sr.vertical_norm,
              sr.concept_key,
              sr.semantic_type,
              sr.sub_type,
              sr.entity,
              sr.description,
              sr.granularity_rank,
              sr.filter_allowed,
              sr.group_by_allowed,
              sr.aggregation_allowed,
              sr.is_identifier,
              sr.is_metric,
              sr.display_priority,
              sr.`sensitive` AS `sensitive`,
              sr.created_at,
              sr.updated_at
            FROM semantic_registry sr
            WHERE sr.id = :id
            LIMIT 1
            """,
            {"id": row_id},
        )
        if not rows:
            raise ForgeError("semantic_registry entry not found", status_code=404)
        return self._normalize_row(rows[0])

    def create_entry(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        data = self._normalize_payload(payload, partial=False)
        try:
            result = self._sql.execute_insert(
                """
                INSERT INTO semantic_registry (
                  vertical,
                  concept_key,
                  semantic_type,
                  sub_type,
                  entity,
                  description,
                  granularity_rank,
                  filter_allowed,
                  group_by_allowed,
                  aggregation_allowed,
                  is_identifier,
                  is_metric,
                  display_priority,
                  `sensitive`
                ) VALUES (
                  :vertical,
                  :concept_key,
                  :semantic_type,
                  :sub_type,
                  :entity,
                  :description,
                  :granularity_rank,
                  :filter_allowed,
                  :group_by_allowed,
                  :aggregation_allowed,
                  :is_identifier,
                  :is_metric,
                  :display_priority,
                  :sensitive
                )
                """,
                data,
            )
        except Exception as exc:
            _raise_write_error(exc)

        if result.lastrowid:
            return self.get_entry(int(result.lastrowid))

        rows = self._sql.execute_query_mappings(
            """
            SELECT id
            FROM semantic_registry
            WHERE vertical_norm = :vertical_norm
              AND concept_key = :concept_key
            ORDER BY id DESC
            LIMIT 1
            """,
            {
                "vertical_norm": _normalize_vertical(data.get("vertical")) or "__global__",
                "concept_key": data["concept_key"],
            },
        )
        if not rows:
            raise ForgeError("Failed to create semantic_registry entry", status_code=500)
        return self.get_entry(int(rows[0]["id"]))

    def update_entry(self, entry_id: int, payload: Dict[str, Any]) -> Dict[str, Any]:
        row_id = _coerce_positive_int(entry_id, field="id")
        data = self._normalize_payload(payload, partial=True)
        if not data:
            return self.get_entry(row_id)

        set_parts = [f"{_sql_col(field)} = :{field}" for field in data.keys()]
        data["id"] = row_id

        try:
            affected = self._sql.execute_write(
                f"""
                UPDATE semantic_registry
                SET {', '.join(set_parts)}
                WHERE id = :id
                """,
                data,
            )
        except Exception as exc:
            _raise_write_error(exc)
            return self.get_entry(row_id)

        if int(affected or 0) <= 0:
            raise ForgeError("semantic_registry entry not found", status_code=404)
        return self.get_entry(row_id)

    def delete_entry(self, entry_id: int) -> None:
        row_id = _coerce_positive_int(entry_id, field="id")
        affected = self._sql.execute_write(
            """
            DELETE FROM semantic_registry
            WHERE id = :id
            """,
            {"id": row_id},
        )
        if int(affected or 0) <= 0:
            raise ForgeError("semantic_registry entry not found", status_code=404)

    def _normalize_payload(self, payload: Dict[str, Any], *, partial: bool) -> Dict[str, Any]:
        if not isinstance(payload, dict):
            raise ForgeError("Invalid JSON body", status_code=400)

        data = {key: value for key, value in payload.items() if key in WRITEABLE_FIELDS}

        if not partial:
            if not str(data.get("concept_key") or "").strip():
                raise ForgeError("concept_key is required", status_code=400)
            if not str(data.get("semantic_type") or "").strip():
                raise ForgeError("semantic_type is required", status_code=400)

        if "concept_key" in data:
            data["concept_key"] = str(data["concept_key"] or "").strip()
            if not data["concept_key"]:
                raise ForgeError("concept_key is required", status_code=400)
            if len(data["concept_key"]) > 150:
                raise ForgeError("concept_key exceeds 150 characters", status_code=400)

        if "semantic_type" in data:
            st = str(data["semantic_type"] or "").strip().lower()
            self._validate_semantic_type(st)
            data["semantic_type"] = st

        for key, max_len in (("vertical", 50), ("sub_type", 200), ("entity", 100)):
            if key in data and data[key] is not None:
                val = str(data[key]).strip()
                data[key] = val or None
                if data[key] is not None and len(data[key]) > max_len:
                    raise ForgeError(f"{key} exceeds {max_len} characters", status_code=400)

        if "description" in data and data["description"] is not None:
            data["description"] = str(data["description"])

        for field in INT_FIELDS:
            if field in data:
                data[field] = int(data[field])

        for field in BOOL_FIELDS:
            if field in data:
                data[field] = _coerce_bool(data[field], field=field)

        if not partial:
            data.setdefault("vertical", None)
            data.setdefault("sub_type", None)
            data.setdefault("entity", None)
            data.setdefault("description", None)
            data.setdefault("granularity_rank", 0)
            data.setdefault("filter_allowed", True)
            data.setdefault("group_by_allowed", True)
            data.setdefault("aggregation_allowed", True)
            data.setdefault("is_identifier", False)
            data.setdefault("is_metric", False)
            data.setdefault("display_priority", 0)
            data.setdefault("sensitive", False)

        return data

    def _normalize_row(self, row: Dict[str, Any]) -> Dict[str, Any]:
        out = dict(row)
        for field in BOOL_FIELDS:
            if field in out:
                out[field] = bool(out[field])
        for field in INT_FIELDS:
            if field in out and out[field] is not None:
                out[field] = int(out[field])
        if "id" in out and out["id"] is not None:
            out["id"] = int(out["id"])
        for field in ("created_at", "updated_at"):
            if field in out:
                out[field] = _json_ready_datetime(out[field])
        return out

    @staticmethod
    def _validate_semantic_type(value: str) -> None:
        if value not in ALLOWED_SEMANTIC_TYPES:
            allowed = ", ".join(sorted(ALLOWED_SEMANTIC_TYPES))
            raise ForgeError(f"semantic_type must be one of: {allowed}", status_code=400)


def _normalize_vertical(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    if text == "":
        return None
    if text.lower() in {"global", "__global__", "null"}:
        return "__global__"
    return text


def _coerce_positive_int(value: Any, *, field: str) -> int:
    try:
        as_int = int(value)
    except Exception as exc:
        raise ForgeError(f"{field} must be a positive integer", status_code=400) from exc
    if as_int <= 0:
        raise ForgeError(f"{field} must be a positive integer", status_code=400)
    return as_int


def _coerce_bool(value: Any, *, field: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "y", "on"}:
            return True
        if lowered in {"0", "false", "no", "n", "off"}:
            return False
    raise ForgeError(f"{field} must be boolean", status_code=400)


def _json_ready_datetime(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return value


def _raise_write_error(exc: Exception) -> None:
    msg = str(exc)
    if "Duplicate entry" in msg:
        raise ForgeError("Duplicate semantic_registry entry", status_code=409) from exc
    raise ForgeError("semantic_registry write failed", status_code=500, details={"message": msg}) from exc


def _sql_col(name: str) -> str:
    if name == "sensitive":
        return "`sensitive`"
    return name
