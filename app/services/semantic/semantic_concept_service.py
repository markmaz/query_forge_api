from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, Optional

from app.adapters.mysql_sql_executor import MySQLSQLExecutor
from app.exceptions.service_error import ServiceError
from app.ports.sql_executor import SQLExecutor
from app.services.semantic.concept_seed import ConceptSeedService
from app.services.semantic.semantic_llm_schema import normalize_concept_key

_ALLOWED_MATCH_KIND = {"exact", "normalized", "prefix", "suffix", "contains", "regex"}
_ALLOWED_VALUE_MATCH_KIND = {"exact", "contains", "prefix", "regex"}
_ALLOWED_RELATIONSHIP_KIND = {"primary", "alternate", "derived", "rollup", "component"}


class SemanticConceptService:
    def __init__(self, *, sql: Optional[SQLExecutor] = None) -> None:
        self._sql = sql or MySQLSQLExecutor()
        self._seed = ConceptSeedService(sql=self._sql)

    def list_concepts(
        self,
        *,
        vertical: Optional[str] = None,
        q: Optional[str] = None,
        semantic_type: Optional[str] = None,
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
            where.append("vertical_norm = :vertical_norm")
            params["vertical_norm"] = vertical_norm

        if semantic_type is not None and str(semantic_type).strip() != "":
            where.append("semantic_type = :semantic_type")
            params["semantic_type"] = str(semantic_type).strip().lower()

        if q is not None and str(q).strip() != "":
            where.append("(LOWER(concept_key) LIKE :q OR LOWER(name) LIKE :q OR LOWER(COALESCE(description, '')) LIKE :q)")
            params["q"] = f"%{str(q).strip().lower()}%"

        where_sql = f"WHERE {' AND '.join(where)}" if where else ""
        rows = self._sql.execute_query_mappings(
            f"""
            SELECT
              id, vertical_norm, concept_key, name, description, semantic_type, sub_type, entity,
              granularity_rank, filter_allowed, group_by_allowed, aggregation_allowed,
              is_identifier, is_metric, display_priority, `sensitive` AS `sensitive`, `status` AS `status`,
              created_at, updated_at
            FROM semantic_concept
            {where_sql}
            ORDER BY display_priority DESC, concept_key ASC
            LIMIT :limit OFFSET :offset
            """,
            params,
        )
        total_rows = self._sql.execute_query_mappings(
            f"""
            SELECT COUNT(*) AS total
            FROM semantic_concept
            {where_sql}
            """,
            {k: v for k, v in params.items() if k not in {"limit", "offset"}},
        )
        total = int((total_rows[0] or {}).get("total") or 0) if total_rows else 0
        return {
            "rows": [_norm_concept_row(r) for r in rows],
            "total": total,
            "page": page_val,
            "page_size": size_val,
        }

    def create_concept(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        data = _normalize_concept_payload(payload, partial=False)
        try:
            result = self._sql.execute_insert(
                """
                INSERT INTO semantic_concept (
                  vertical_norm, concept_key, name, description, semantic_type, sub_type, entity,
                  granularity_rank, filter_allowed, group_by_allowed, aggregation_allowed,
                  is_identifier, is_metric, display_priority, `sensitive`, `status`
                ) VALUES (
                  :vertical_norm, :concept_key, :name, :description, :semantic_type, :sub_type, :entity,
                  :granularity_rank, :filter_allowed, :group_by_allowed, :aggregation_allowed,
                  :is_identifier, :is_metric, :display_priority, :sensitive, :status
                )
                """,
                data,
            )
        except Exception as exc:
            _raise_write_error(exc, "concept")

        if not result.lastrowid:
            raise ServiceError("failed to create concept", status_code=500)
        return self.get_concept(int(result.lastrowid))

    def patch_concept(self, concept_id: int, payload: Dict[str, Any]) -> Dict[str, Any]:
        concept_id = _as_pos_int(concept_id, "concept_id")
        data = _normalize_concept_payload(payload, partial=True)
        if not data:
            return self.get_concept(concept_id)
        set_parts = [f"{_sql_col(k)} = :{k}" for k in data.keys()]
        data["id"] = concept_id
        try:
            affected = self._sql.execute_write(
                f"""
                UPDATE semantic_concept
                SET {', '.join(set_parts)}
                WHERE id = :id
                """,
                data,
            )
        except Exception as exc:
            _raise_write_error(exc, "concept")
            affected = 0
        if int(affected or 0) <= 0:
            raise ServiceError("concept not found", status_code=404)
        return self.get_concept(concept_id)

    def get_concept(self, concept_id: int) -> Dict[str, Any]:
        concept_id = _as_pos_int(concept_id, "concept_id")
        rows = self._sql.execute_query_mappings(
            """
            SELECT
              id, vertical_norm, concept_key, name, description, semantic_type, sub_type, entity,
              granularity_rank, filter_allowed, group_by_allowed, aggregation_allowed,
              is_identifier, is_metric, display_priority, `sensitive` AS `sensitive`, `status` AS `status`,
              created_at, updated_at
            FROM semantic_concept
            WHERE id = :id
            LIMIT 1
            """,
            {"id": concept_id},
        )
        if not rows:
            raise ServiceError("concept not found", status_code=404)
        return _norm_concept_row(rows[0])

    def delete_concept(self, concept_id: int) -> None:
        concept_id = _as_pos_int(concept_id, "concept_id")
        try:
            affected = self._sql.execute_write(
                """
                DELETE FROM semantic_concept
                WHERE id = :id
                """,
                {"id": concept_id},
            )
        except Exception as exc:
            _raise_write_error(exc, "concept")
            affected = 0
        if int(affected or 0) <= 0:
            raise ServiceError("concept not found", status_code=404)

    def list_aliases(
        self,
        *,
        vertical: Optional[str] = None,
        concept_key: Optional[str] = None,
        q: Optional[str] = None,
    ) -> Dict[str, Any]:
        where = []
        params: Dict[str, Any] = {}

        vertical_norm = _normalize_vertical(vertical)
        if vertical_norm is not None:
            where.append("vertical_norm = :vertical_norm")
            params["vertical_norm"] = vertical_norm

        if concept_key is not None and str(concept_key).strip() != "":
            where.append("concept_key = :concept_key")
            params["concept_key"] = normalize_concept_key(str(concept_key))

        if q is not None and str(q).strip() != "":
            where.append("(LOWER(alias_key) LIKE :q OR LOWER(concept_key) LIKE :q)")
            params["q"] = f"%{str(q).strip().lower()}%"

        where_sql = f"WHERE {' AND '.join(where)}" if where else ""
        rows = self._sql.execute_query_mappings(
            f"""
            SELECT id, vertical_norm, alias_key, concept_key, match_kind, weight, created_at
            FROM semantic_concept_alias
            {where_sql}
            ORDER BY weight DESC, id ASC
            """,
            params,
        )
        return {"rows": [_norm_alias_row(r) for r in rows], "total": len(rows)}

    def create_alias(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        data = _normalize_alias_payload(payload)
        self._ensure_concept_exists(vertical_norm=data["vertical_norm"], concept_key=data["concept_key"])
        try:
            result = self._sql.execute_insert(
                """
                INSERT INTO semantic_concept_alias (
                  vertical_norm, alias_key, concept_key, match_kind, weight
                ) VALUES (
                  :vertical_norm, :alias_key, :concept_key, :match_kind, :weight
                )
                """,
                data,
            )
        except Exception as exc:
            _raise_write_error(exc, "alias")

        if not result.lastrowid:
            raise ServiceError("failed to create alias", status_code=500)

        rows = self._sql.execute_query_mappings(
            """
            SELECT id, vertical_norm, alias_key, concept_key, match_kind, weight, created_at
            FROM semantic_concept_alias
            WHERE id = :id
            LIMIT 1
            """,
            {"id": int(result.lastrowid)},
        )
        return _norm_alias_row(rows[0])

    def get_alias(self, alias_id: int) -> Dict[str, Any]:
        alias_id = _as_pos_int(alias_id, "alias_id")
        rows = self._sql.execute_query_mappings(
            """
            SELECT id, vertical_norm, alias_key, concept_key, match_kind, weight, created_at
            FROM semantic_concept_alias
            WHERE id = :id
            LIMIT 1
            """,
            {"id": alias_id},
        )
        if not rows:
            raise ServiceError("alias not found", status_code=404)
        return _norm_alias_row(rows[0])

    def patch_alias(self, alias_id: int, payload: Dict[str, Any]) -> Dict[str, Any]:
        alias_id = _as_pos_int(alias_id, "alias_id")
        data = _normalize_alias_patch_payload(payload)
        if not data:
            return self.get_alias(alias_id)
        if "vertical_norm" in data and "concept_key" in data:
            self._ensure_concept_exists(vertical_norm=data["vertical_norm"], concept_key=data["concept_key"])
        elif "concept_key" in data:
            current = self.get_alias(alias_id)
            self._ensure_concept_exists(vertical_norm=current["vertical_norm"], concept_key=data["concept_key"])
        set_parts = [f"{k} = :{k}" for k in data.keys()]
        data["id"] = alias_id
        try:
            affected = self._sql.execute_write(
                f"""
                UPDATE semantic_concept_alias
                SET {', '.join(set_parts)}
                WHERE id = :id
                """,
                data,
            )
        except Exception as exc:
            _raise_write_error(exc, "alias")
            affected = 0
        if int(affected or 0) <= 0:
            raise ServiceError("alias not found", status_code=404)
        return self.get_alias(alias_id)

    def delete_alias(self, alias_id: int) -> None:
        alias_id = _as_pos_int(alias_id, "alias_id")
        try:
            affected = self._sql.execute_write(
                """
                DELETE FROM semantic_concept_alias
                WHERE id = :id
                """,
                {"id": alias_id},
            )
        except Exception as exc:
            _raise_write_error(exc, "alias")
            affected = 0
        if int(affected or 0) <= 0:
            raise ServiceError("alias not found", status_code=404)

    def list_value_aliases(
        self,
        *,
        vertical: Optional[str] = None,
        semantic_concept_id: Optional[int] = None,
        q: Optional[str] = None,
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
            where.append("va.vertical_norm = :vertical_norm")
            params["vertical_norm"] = vertical_norm
        if semantic_concept_id is not None:
            where.append("va.semantic_concept_id = :semantic_concept_id")
            params["semantic_concept_id"] = _as_pos_int(semantic_concept_id, "semantic_concept_id")
        if q is not None and str(q).strip():
            where.append("(LOWER(va.alias_value) LIKE :q OR LOWER(va.canonical_value) LIKE :q)")
            params["q"] = f"%{str(q).strip().lower()}%"

        where_sql = f"WHERE {' AND '.join(where)}" if where else ""
        rows = self._sql.execute_query_mappings(
            f"""
            SELECT
              va.id,
              va.vertical_norm,
              va.semantic_concept_id,
              sc.concept_key,
              va.canonical_value,
              va.alias_value,
              va.match_kind,
              va.weight,
              va.created_at
            FROM semantic_value_alias va
            JOIN semantic_concept sc ON sc.id = va.semantic_concept_id
            {where_sql}
            ORDER BY va.weight DESC, va.id ASC
            LIMIT :limit OFFSET :offset
            """,
            params,
        )
        total_rows = self._sql.execute_query_mappings(
            f"""
            SELECT COUNT(*) AS total
            FROM semantic_value_alias va
            {where_sql}
            """,
            {k: v for k, v in params.items() if k not in {"limit", "offset"}},
        )
        total = int((total_rows[0] or {}).get("total") or 0) if total_rows else 0
        return {
            "rows": [_norm_value_alias_row(r) for r in rows],
            "total": total,
            "page": page_val,
            "page_size": size_val,
        }

    def create_value_alias(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        data = _normalize_value_alias_payload(payload, partial=False)
        self._ensure_concept_id_exists(data["semantic_concept_id"])
        try:
            result = self._sql.execute_insert(
                """
                INSERT INTO semantic_value_alias (
                  vertical_norm, semantic_concept_id, canonical_value, alias_value, match_kind, weight
                ) VALUES (
                  :vertical_norm, :semantic_concept_id, :canonical_value, :alias_value, :match_kind, :weight
                )
                """,
                data,
            )
        except Exception as exc:
            _raise_write_error(exc, "value_alias")
        if not result.lastrowid:
            raise ServiceError("failed to create value_alias", status_code=500)
        return self.get_value_alias(int(result.lastrowid))

    def get_value_alias(self, value_alias_id: int) -> Dict[str, Any]:
        value_alias_id = _as_pos_int(value_alias_id, "value_alias_id")
        rows = self._sql.execute_query_mappings(
            """
            SELECT
              va.id,
              va.vertical_norm,
              va.semantic_concept_id,
              sc.concept_key,
              va.canonical_value,
              va.alias_value,
              va.match_kind,
              va.weight,
              va.created_at
            FROM semantic_value_alias va
            JOIN semantic_concept sc ON sc.id = va.semantic_concept_id
            WHERE va.id = :id
            LIMIT 1
            """,
            {"id": value_alias_id},
        )
        if not rows:
            raise ServiceError("value_alias not found", status_code=404)
        return _norm_value_alias_row(rows[0])

    def patch_value_alias(self, value_alias_id: int, payload: Dict[str, Any]) -> Dict[str, Any]:
        value_alias_id = _as_pos_int(value_alias_id, "value_alias_id")
        data = _normalize_value_alias_payload(payload, partial=True)
        if not data:
            return self.get_value_alias(value_alias_id)
        if "semantic_concept_id" in data:
            self._ensure_concept_id_exists(data["semantic_concept_id"])
        set_parts = [f"{k} = :{k}" for k in data.keys()]
        data["id"] = value_alias_id
        try:
            affected = self._sql.execute_write(
                f"""
                UPDATE semantic_value_alias
                SET {', '.join(set_parts)}
                WHERE id = :id
                """,
                data,
            )
        except Exception as exc:
            _raise_write_error(exc, "value_alias")
            affected = 0
        if int(affected or 0) <= 0:
            raise ServiceError("value_alias not found", status_code=404)
        return self.get_value_alias(value_alias_id)

    def delete_value_alias(self, value_alias_id: int) -> None:
        value_alias_id = _as_pos_int(value_alias_id, "value_alias_id")
        try:
            affected = self._sql.execute_write(
                """
                DELETE FROM semantic_value_alias
                WHERE id = :id
                """,
                {"id": value_alias_id},
            )
        except Exception as exc:
            _raise_write_error(exc, "value_alias")
            affected = 0
        if int(affected or 0) <= 0:
            raise ServiceError("value_alias not found", status_code=404)

    def list_concept_column_maps(
        self,
        *,
        vertical: Optional[str] = None,
        semantic_concept_id: Optional[int] = None,
        model_column_id: Optional[int] = None,
        relationship_kind: Optional[str] = None,
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
            where.append("m.vertical_norm = :vertical_norm")
            params["vertical_norm"] = vertical_norm
        if semantic_concept_id is not None:
            where.append("m.semantic_concept_id = :semantic_concept_id")
            params["semantic_concept_id"] = _as_pos_int(semantic_concept_id, "semantic_concept_id")
        if model_column_id is not None:
            where.append("m.model_column_id = :model_column_id")
            params["model_column_id"] = _as_pos_int(model_column_id, "model_column_id")
        if relationship_kind is not None and str(relationship_kind).strip():
            rel = str(relationship_kind).strip().lower()
            if rel not in _ALLOWED_RELATIONSHIP_KIND:
                raise ServiceError("invalid relationship_kind", status_code=400)
            where.append("m.relationship_kind = :relationship_kind")
            params["relationship_kind"] = rel

        where_sql = f"WHERE {' AND '.join(where)}" if where else ""
        rows = self._sql.execute_query_mappings(
            f"""
            SELECT
              m.id,
              m.vertical_norm,
              m.semantic_concept_id,
              sc.concept_key,
              sc.name AS concept_name,
              m.model_column_id,
              mc.column_name,
              mt.name AS model_table_name,
              m.relationship_kind,
              m.weight,
              m.created_at
            FROM model_column_semantic_concept_map m
            JOIN semantic_concept sc ON sc.id = m.semantic_concept_id
            JOIN model_column mc ON mc.id = m.model_column_id
            LEFT JOIN model_table mt ON mt.id = mc.model_table_id
            {where_sql}
            ORDER BY m.weight DESC, m.id ASC
            LIMIT :limit OFFSET :offset
            """,
            params,
        )
        total_rows = self._sql.execute_query_mappings(
            f"""
            SELECT COUNT(*) AS total
            FROM model_column_semantic_concept_map m
            {where_sql}
            """,
            {k: v for k, v in params.items() if k not in {"limit", "offset"}},
        )
        total = int((total_rows[0] or {}).get("total") or 0) if total_rows else 0
        return {
            "rows": [_norm_concept_column_map_row(r) for r in rows],
            "total": total,
            "page": page_val,
            "page_size": size_val,
        }

    def create_concept_column_map(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        data = _normalize_concept_column_map_payload(payload, partial=False)
        self._ensure_concept_id_exists(data["semantic_concept_id"])
        self._ensure_model_column_exists(data["model_column_id"])
        try:
            result = self._sql.execute_insert(
                """
                INSERT INTO model_column_semantic_concept_map (
                  vertical_norm, semantic_concept_id, model_column_id, relationship_kind, weight
                ) VALUES (
                  :vertical_norm, :semantic_concept_id, :model_column_id, :relationship_kind, :weight
                )
                """,
                data,
            )
        except Exception as exc:
            _raise_write_error(exc, "concept_column_map")
        if not result.lastrowid:
            raise ServiceError("failed to create concept_column_map", status_code=500)
        return self.get_concept_column_map(int(result.lastrowid))

    def get_concept_column_map(self, map_id: int) -> Dict[str, Any]:
        map_id = _as_pos_int(map_id, "map_id")
        rows = self._sql.execute_query_mappings(
            """
            SELECT
              m.id,
              m.vertical_norm,
              m.semantic_concept_id,
              sc.concept_key,
              sc.name AS concept_name,
              m.model_column_id,
              mc.column_name,
              mt.name AS model_table_name,
              m.relationship_kind,
              m.weight,
              m.created_at
            FROM model_column_semantic_concept_map m
            JOIN semantic_concept sc ON sc.id = m.semantic_concept_id
            JOIN model_column mc ON mc.id = m.model_column_id
            LEFT JOIN model_table mt ON mt.id = mc.model_table_id
            WHERE m.id = :id
            LIMIT 1
            """,
            {"id": map_id},
        )
        if not rows:
            raise ServiceError("concept_column_map not found", status_code=404)
        return _norm_concept_column_map_row(rows[0])

    def patch_concept_column_map(self, map_id: int, payload: Dict[str, Any]) -> Dict[str, Any]:
        map_id = _as_pos_int(map_id, "map_id")
        data = _normalize_concept_column_map_payload(payload, partial=True)
        if not data:
            return self.get_concept_column_map(map_id)
        if "semantic_concept_id" in data:
            self._ensure_concept_id_exists(data["semantic_concept_id"])
        if "model_column_id" in data:
            self._ensure_model_column_exists(data["model_column_id"])
        set_parts = [f"{k} = :{k}" for k in data.keys()]
        data["id"] = map_id
        try:
            affected = self._sql.execute_write(
                f"""
                UPDATE model_column_semantic_concept_map
                SET {', '.join(set_parts)}
                WHERE id = :id
                """,
                data,
            )
        except Exception as exc:
            _raise_write_error(exc, "concept_column_map")
            affected = 0
        if int(affected or 0) <= 0:
            raise ServiceError("concept_column_map not found", status_code=404)
        return self.get_concept_column_map(map_id)

    def delete_concept_column_map(self, map_id: int) -> None:
        map_id = _as_pos_int(map_id, "map_id")
        try:
            affected = self._sql.execute_write(
                """
                DELETE FROM model_column_semantic_concept_map
                WHERE id = :id
                """,
                {"id": map_id},
            )
        except Exception as exc:
            _raise_write_error(exc, "concept_column_map")
            affected = 0
        if int(affected or 0) <= 0:
            raise ServiceError("concept_column_map not found", status_code=404)

    def seed(self, vertical: str) -> Dict[str, Any]:
        return self._seed.ensure_seeded(vertical)

    def _ensure_concept_exists(self, *, vertical_norm: str, concept_key: str) -> None:
        rows = self._sql.execute_query_mappings(
            """
            SELECT id
            FROM semantic_concept
            WHERE vertical_norm = :vertical_norm
              AND concept_key = :concept_key
            LIMIT 1
            """,
            {"vertical_norm": vertical_norm, "concept_key": concept_key},
        )
        if not rows:
            raise ServiceError("concept_key not found for vertical", status_code=400)

    def _ensure_concept_id_exists(self, concept_id: int) -> None:
        rows = self._sql.execute_query_mappings(
            """
            SELECT id
            FROM semantic_concept
            WHERE id = :id
            LIMIT 1
            """,
            {"id": _as_pos_int(concept_id, "semantic_concept_id")},
        )
        if not rows:
            raise ServiceError("semantic_concept_id not found", status_code=400)

    def _ensure_model_column_exists(self, model_column_id: int) -> None:
        rows = self._sql.execute_query_mappings(
            """
            SELECT id
            FROM model_column
            WHERE id = :id
            LIMIT 1
            """,
            {"id": _as_pos_int(model_column_id, "model_column_id")},
        )
        if not rows:
            raise ServiceError("model_column_id not found", status_code=400)


def _normalize_vertical(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip().lower()
    if text == "":
        return None
    return text


def _as_pos_int(value: Any, field: str) -> int:
    try:
        out = int(value)
    except Exception as exc:
        raise ServiceError(f"{field} must be a positive integer", status_code=400) from exc
    if out <= 0:
        raise ServiceError(f"{field} must be a positive integer", status_code=400)
    return out


def _to_bool(value: Any, field: str) -> int:
    if isinstance(value, bool):
        return 1 if value else 0
    if isinstance(value, (int, float)):
        return 1 if bool(value) else 0
    if isinstance(value, str):
        low = value.strip().lower()
        if low in {"1", "true", "yes", "on", "y"}:
            return 1
        if low in {"0", "false", "no", "off", "n"}:
            return 0
    raise ServiceError(f"{field} must be boolean", status_code=400)


def _normalize_concept_payload(payload: Dict[str, Any], *, partial: bool) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise ServiceError("invalid json body", status_code=400)

    allowed = {
        "vertical_norm",
        "concept_key",
        "name",
        "description",
        "semantic_type",
        "sub_type",
        "entity",
        "granularity_rank",
        "filter_allowed",
        "group_by_allowed",
        "aggregation_allowed",
        "is_identifier",
        "is_metric",
        "display_priority",
        "sensitive",
        "status",
    }
    out = {k: v for k, v in payload.items() if k in allowed}

    if not partial:
        for req in ("vertical_norm", "concept_key", "name", "semantic_type"):
            if not str(out.get(req) or "").strip():
                raise ServiceError(f"{req} is required", status_code=400)

    if "vertical_norm" in out:
        out["vertical_norm"] = str(out["vertical_norm"] or "").strip().lower()
    if "concept_key" in out:
        out["concept_key"] = normalize_concept_key(str(out["concept_key"] or ""))
    if "name" in out:
        out["name"] = str(out["name"] or "").strip()
    if "description" in out and out["description"] is not None:
        out["description"] = str(out["description"])
    if "semantic_type" in out:
        out["semantic_type"] = str(out["semantic_type"] or "").strip().lower()
    if "sub_type" in out and out["sub_type"] is not None:
        out["sub_type"] = str(out["sub_type"]).strip() or None
    if "entity" in out and out["entity"] is not None:
        out["entity"] = str(out["entity"]).strip() or None
    if "status" in out:
        out["status"] = str(out["status"] or "").strip().lower() or "active"

    for k in ("granularity_rank", "display_priority"):
        if k in out:
            out[k] = int(out[k])
    for k in (
        "filter_allowed",
        "group_by_allowed",
        "aggregation_allowed",
        "is_identifier",
        "is_metric",
        "sensitive",
    ):
        if k in out:
            out[k] = _to_bool(out[k], k)

    if not partial:
        out.setdefault("description", None)
        out.setdefault("sub_type", None)
        out.setdefault("entity", None)
        out.setdefault("granularity_rank", 0)
        out.setdefault("filter_allowed", 1)
        out.setdefault("group_by_allowed", 1)
        out.setdefault("aggregation_allowed", 0)
        out.setdefault("is_identifier", 0)
        out.setdefault("is_metric", 0)
        out.setdefault("display_priority", 0)
        out.setdefault("sensitive", 0)
        out.setdefault("status", "active")

    return out


def _normalize_alias_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise ServiceError("invalid json body", status_code=400)

    for req in ("vertical_norm", "alias_key", "concept_key"):
        if not str(payload.get(req) or "").strip():
            raise ServiceError(f"{req} is required", status_code=400)

    match_kind = str(payload.get("match_kind") or "exact").strip().lower()
    if match_kind not in _ALLOWED_MATCH_KIND:
        raise ServiceError("match_kind must be exact|normalized|prefix|suffix|contains|regex", status_code=400)

    try:
        weight = float(payload.get("weight", 1.0))
    except Exception as exc:
        raise ServiceError("weight must be numeric", status_code=400) from exc

    return {
        "vertical_norm": str(payload.get("vertical_norm") or "").strip().lower(),
        "alias_key": str(payload.get("alias_key") or "").strip().lower(),
        "concept_key": normalize_concept_key(str(payload.get("concept_key") or "")),
        "match_kind": match_kind,
        "weight": weight,
    }


def _normalize_alias_patch_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise ServiceError("invalid json body", status_code=400)
    allowed = {"vertical_norm", "alias_key", "concept_key", "match_kind", "weight"}
    out = {k: v for k, v in payload.items() if k in allowed}
    if "vertical_norm" in out:
        out["vertical_norm"] = str(out["vertical_norm"] or "").strip().lower()
    if "alias_key" in out:
        out["alias_key"] = str(out["alias_key"] or "").strip().lower()
    if "concept_key" in out:
        out["concept_key"] = normalize_concept_key(str(out["concept_key"] or ""))
    if "match_kind" in out:
        match_kind = str(out["match_kind"] or "").strip().lower()
        if match_kind not in _ALLOWED_MATCH_KIND:
            raise ServiceError("match_kind must be exact|normalized|prefix|suffix|contains|regex", status_code=400)
        out["match_kind"] = match_kind
    if "weight" in out:
        try:
            out["weight"] = float(out["weight"])
        except Exception as exc:
            raise ServiceError("weight must be numeric", status_code=400) from exc
    return out


def _normalize_value_alias_payload(payload: Dict[str, Any], *, partial: bool) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise ServiceError("invalid json body", status_code=400)
    allowed = {"vertical_norm", "semantic_concept_id", "canonical_value", "alias_value", "match_kind", "weight"}
    out = {k: v for k, v in payload.items() if k in allowed}
    if not partial:
        for req in ("vertical_norm", "semantic_concept_id", "canonical_value", "alias_value"):
            if not str(out.get(req) or "").strip():
                raise ServiceError(f"{req} is required", status_code=400)
    if "vertical_norm" in out:
        out["vertical_norm"] = str(out["vertical_norm"] or "").strip().lower()
    if "semantic_concept_id" in out:
        out["semantic_concept_id"] = _as_pos_int(out["semantic_concept_id"], "semantic_concept_id")
    if "canonical_value" in out:
        out["canonical_value"] = str(out["canonical_value"] or "").strip()
    if "alias_value" in out:
        out["alias_value"] = str(out["alias_value"] or "").strip()
    if "match_kind" in out:
        mk = str(out["match_kind"] or "").strip().lower()
        if mk not in _ALLOWED_VALUE_MATCH_KIND:
            raise ServiceError("match_kind must be exact|contains|prefix|regex", status_code=400)
        out["match_kind"] = mk
    if "weight" in out:
        try:
            out["weight"] = float(out["weight"])
        except Exception as exc:
            raise ServiceError("weight must be numeric", status_code=400) from exc
    if not partial:
        out.setdefault("match_kind", "contains")
        out.setdefault("weight", 1.0)
    return out


def _normalize_concept_column_map_payload(payload: Dict[str, Any], *, partial: bool) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise ServiceError("invalid json body", status_code=400)
    allowed = {"vertical_norm", "semantic_concept_id", "model_column_id", "relationship_kind", "weight"}
    out = {k: v for k, v in payload.items() if k in allowed}
    if not partial:
        for req in ("vertical_norm", "semantic_concept_id", "model_column_id"):
            if not str(out.get(req) or "").strip():
                raise ServiceError(f"{req} is required", status_code=400)
    if "vertical_norm" in out:
        out["vertical_norm"] = str(out["vertical_norm"] or "").strip().lower()
    if "semantic_concept_id" in out:
        out["semantic_concept_id"] = _as_pos_int(out["semantic_concept_id"], "semantic_concept_id")
    if "model_column_id" in out:
        out["model_column_id"] = _as_pos_int(out["model_column_id"], "model_column_id")
    if "relationship_kind" in out:
        rel = str(out["relationship_kind"] or "").strip().lower()
        if rel not in _ALLOWED_RELATIONSHIP_KIND:
            raise ServiceError("relationship_kind must be primary|alternate|derived|rollup|component", status_code=400)
        out["relationship_kind"] = rel
    if "weight" in out:
        try:
            out["weight"] = float(out["weight"])
        except Exception as exc:
            raise ServiceError("weight must be numeric", status_code=400) from exc
    if not partial:
        out.setdefault("relationship_kind", "primary")
        out.setdefault("weight", 1.0)
    return out


def _norm_concept_row(row: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(row)
    for k in ("id", "granularity_rank", "display_priority"):
        if out.get(k) is not None:
            out[k] = int(out[k])
    for k in ("filter_allowed", "group_by_allowed", "aggregation_allowed", "is_identifier", "is_metric", "sensitive"):
        if k in out:
            out[k] = bool(out[k])
    _normalize_temporal_fields(out)
    return out


def _norm_alias_row(row: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(row)
    if out.get("id") is not None:
        out["id"] = int(out["id"])
    if out.get("weight") is not None:
        out["weight"] = float(out["weight"])
    _normalize_temporal_fields(out)
    return out


def _norm_value_alias_row(row: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(row)
    for key in ("id", "semantic_concept_id"):
        if out.get(key) is not None:
            out[key] = int(out[key])
    if out.get("weight") is not None:
        out["weight"] = float(out["weight"])
    _normalize_temporal_fields(out)
    return out


def _norm_concept_column_map_row(row: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(row)
    for key in ("id", "semantic_concept_id", "model_column_id"):
        if out.get(key) is not None:
            out[key] = int(out[key])
    if out.get("weight") is not None:
        out["weight"] = float(out["weight"])
    _normalize_temporal_fields(out)
    return out


def _normalize_temporal_fields(row: Dict[str, Any]) -> None:
    for key, value in list(row.items()):
        if isinstance(value, (datetime, date)):
            row[key] = value.isoformat()


def _raise_write_error(exc: Exception, kind: str) -> None:
    msg = str(exc)
    if "Duplicate entry" in msg:
        raise ServiceError(f"duplicate {kind}", status_code=409) from exc
    raise ServiceError(f"{kind} write failed", status_code=500, details={"message": msg}) from exc


def _sql_col(name: str) -> str:
    if name in {"sensitive", "status"}:
        return f"`{name}`"
    return name
