from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

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
}

BOOLEAN_FIELDS = {
    "filter_allowed",
    "group_by_allowed",
    "aggregation_allowed",
    "identifier",
    "metric",
    "sensitive",
}

INT_FIELDS = {"granularity_rank", "display_priority"}
PATCHABLE_FIELDS = {
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
    "identifier",
    "metric",
    "display_priority",
    "sensitive",
}


class SemanticRegistryService:
    def __init__(self, *, sql: Optional[ForgeQueryPort] = None) -> None:
        self._sql = sql or ForgeMetaSQL()

    def list_entries(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        vertical: Optional[str] = None,
        semantic_type: Optional[str] = None,
        q: Optional[str] = None,
    ) -> Tuple[List[Dict[str, Any]], int]:
        where: List[str] = []
        params: Dict[str, Any] = {}

        if vertical is not None and vertical.strip() != "":
            where.append("vertical = :vertical")
            params["vertical"] = vertical.strip()
        if semantic_type is not None and semantic_type.strip() != "":
            st = semantic_type.strip().lower()
            self._validate_semantic_type(st)
            where.append("semantic_type = :semantic_type")
            params["semantic_type"] = st
        if q is not None and q.strip() != "":
            where.append(
                "("
                "LOWER(concept_key) LIKE :q OR LOWER(COALESCE(sub_type, '')) LIKE :q OR "
                "LOWER(COALESCE(entity, '')) LIKE :q OR LOWER(COALESCE(description, '')) LIKE :q"
                ")"
            )
            params["q"] = f"%{q.strip().lower()}%"

        where_sql = f"WHERE {' AND '.join(where)}" if where else ""
        safe_limit = max(1, min(int(limit), 500))
        safe_offset = max(0, int(offset))
        params["limit"] = safe_limit
        params["offset"] = safe_offset

        rows = self._sql.execute_query_mappings(
            f"""
            SELECT
              id, vertical, concept_key, semantic_type, sub_type, entity, description,
              granularity_rank, filter_allowed, group_by_allowed, aggregation_allowed,
              identifier, metric, display_priority, sensitive, created_at, updated_at
            FROM semantic_registry
            {where_sql}
            ORDER BY display_priority DESC, granularity_rank ASC, concept_key ASC
            LIMIT :limit OFFSET :offset
            """,
            params,
        )
        total_rows = self._sql.execute_query_mappings(
            f"""
            SELECT COUNT(*) AS total
            FROM semantic_registry
            {where_sql}
            """,
            {k: v for k, v in params.items() if k not in {"limit", "offset"}},
        )
        total = int((total_rows[0] or {}).get("total") or 0) if total_rows else 0
        return [self._normalize_row(row) for row in rows], total

    def get_entry(self, entry_id: str) -> Dict[str, Any]:
        rows = self._sql.execute_query_mappings(
            """
            SELECT
              id, vertical, concept_key, semantic_type, sub_type, entity, description,
              granularity_rank, filter_allowed, group_by_allowed, aggregation_allowed,
              identifier, metric, display_priority, sensitive, created_at, updated_at
            FROM semantic_registry
            WHERE id = :id
            LIMIT 1
            """,
            {"id": self._validate_uuid(entry_id)},
        )
        if not rows:
            raise ForgeError("semantic_registry entry not found", status_code=404)
        return self._normalize_row(rows[0])

    def create_entry(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        clean = self._normalize_payload(payload, partial=False)
        self._sql.execute_write(
            """
            INSERT INTO semantic_registry (
              vertical, concept_key, semantic_type, sub_type, entity, description,
              granularity_rank, filter_allowed, group_by_allowed, aggregation_allowed,
              identifier, metric, display_priority, sensitive
            ) VALUES (
              :vertical, :concept_key, :semantic_type, :sub_type, :entity, :description,
              :granularity_rank, :filter_allowed, :group_by_allowed, :aggregation_allowed,
              :identifier, :metric, :display_priority, :sensitive
            )
            """,
            clean,
        )
        rows = self._sql.execute_query_mappings(
            """
            SELECT id
            FROM semantic_registry
            WHERE concept_key = :concept_key
            LIMIT 1
            """,
            {"concept_key": clean["concept_key"]},
        )
        if not rows:
            raise ForgeError("Failed to create semantic_registry entry", status_code=500)
        return self.get_entry(str(rows[0]["id"]))

    def update_entry(self, entry_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        entry_uuid = self._validate_uuid(entry_id)
        clean = self._normalize_payload(payload, partial=True)
        if not clean:
            return self.get_entry(entry_uuid)

        set_parts = [f"{field} = :{field}" for field in clean.keys()]
        set_parts.append("updated_at = CURRENT_TIMESTAMP")
        clean["id"] = entry_uuid

        affected = self._sql.execute_write(
            f"""
            UPDATE semantic_registry
            SET {", ".join(set_parts)}
            WHERE id = :id
            """,
            clean,
        )
        if affected <= 0:
            raise ForgeError("semantic_registry entry not found", status_code=404)
        return self.get_entry(entry_uuid)

    def delete_entry(self, entry_id: str) -> None:
        affected = self._sql.execute_write(
            """
            DELETE FROM semantic_registry
            WHERE id = :id
            """,
            {"id": self._validate_uuid(entry_id)},
        )
        if affected <= 0:
            raise ForgeError("semantic_registry entry not found", status_code=404)

    def _normalize_payload(self, payload: Dict[str, Any], *, partial: bool) -> Dict[str, Any]:
        if not isinstance(payload, dict):
            raise ForgeError("Invalid JSON body", status_code=400)

        data: Dict[str, Any] = {}
        for key, value in payload.items():
            if key not in PATCHABLE_FIELDS:
                continue
            data[key] = value

        if not partial:
            if "concept_key" not in data or not str(data["concept_key"] or "").strip():
                raise ForgeError("concept_key is required", status_code=400)
            if "semantic_type" not in data or not str(data["semantic_type"] or "").strip():
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

        for key in ("vertical", "sub_type", "entity"):
            if key in data and data[key] is not None:
                data[key] = str(data[key]).strip()
                if data[key] == "":
                    data[key] = None

        if "vertical" in data and data["vertical"] is not None and len(data["vertical"]) > 50:
            raise ForgeError("vertical exceeds 50 characters", status_code=400)
        if "sub_type" in data and data["sub_type"] is not None and len(data["sub_type"]) > 200:
            raise ForgeError("sub_type exceeds 200 characters", status_code=400)
        if "entity" in data and data["entity"] is not None and len(data["entity"]) > 100:
            raise ForgeError("entity exceeds 100 characters", status_code=400)

        if "description" in data and data["description"] is not None:
            data["description"] = str(data["description"])

        for key in INT_FIELDS:
            if key in data:
                data[key] = int(data[key])

        for key in BOOLEAN_FIELDS:
            if key in data:
                data[key] = self._to_bool(data[key])

        if not partial:
            data.setdefault("vertical", None)
            data.setdefault("sub_type", None)
            data.setdefault("entity", None)
            data.setdefault("description", None)
            data.setdefault("granularity_rank", 0)
            data.setdefault("filter_allowed", True)
            data.setdefault("group_by_allowed", True)
            data.setdefault("aggregation_allowed", True)
            data.setdefault("identifier", False)
            data.setdefault("metric", False)
            data.setdefault("display_priority", 0)
            data.setdefault("sensitive", False)

        return data

    def _normalize_row(self, row: Dict[str, Any]) -> Dict[str, Any]:
        out = dict(row)
        for key in BOOLEAN_FIELDS:
            out[key] = self._to_bool(out.get(key))
        for key in INT_FIELDS:
            value = out.get(key)
            out[key] = int(value) if value is not None else 0
        return out

    @staticmethod
    def _to_bool(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return int(value) != 0
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "y", "on"}
        return False

    @staticmethod
    def _validate_uuid(value: str) -> str:
        text = str(value or "").strip()
        if not text or len(text) > 36:
            raise ForgeError("Invalid semantic_registry id", status_code=400)
        return text

    @staticmethod
    def _validate_semantic_type(value: str) -> None:
        if value not in ALLOWED_SEMANTIC_TYPES:
            raise ForgeError(
                f"Invalid semantic_type '{value}'. Allowed: {', '.join(sorted(ALLOWED_SEMANTIC_TYPES))}",
                status_code=400,
            )

