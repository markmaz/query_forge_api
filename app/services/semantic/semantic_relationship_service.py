from __future__ import annotations

from collections import deque
from datetime import date, datetime
from typing import Any, Dict, Optional

from sqlalchemy.exc import SQLAlchemyError

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.exceptions.forge_error import ForgeError
from app.ports.sql_executor import ForgeQueryPort
from app.services.semantic.semantic_registry_service import _coerce_positive_int, _normalize_vertical

_CYCLE_GUARD_RELATIONSHIP_TYPES = frozenset({"depends_on"})


class SemanticRelationshipService:
    def __init__(self, *, sql: Optional[ForgeQueryPort] = None) -> None:
        self._sql = sql or ForgeMetaSQL()

    def list_relationships(
        self,
        *,
        vertical: Optional[str] = None,
        parent_id: Optional[int] = None,
        child_id: Optional[int] = None,
        relationship_type: Optional[str] = None,
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
            where.append("sp.vertical_norm = :vertical_norm")
            params["vertical_norm"] = vertical_norm

        if parent_id is not None:
            where.append("sr.parent_concept_id = :parent_id")
            params["parent_id"] = _coerce_positive_int(parent_id, field="parent_id")

        if child_id is not None:
            where.append("sr.child_concept_id = :child_id")
            params["child_id"] = _coerce_positive_int(child_id, field="child_id")

        if relationship_type is not None and str(relationship_type).strip() != "":
            where.append("LOWER(sr.relationship_type) = :relationship_type")
            params["relationship_type"] = str(relationship_type).strip().lower()

        where_sql = f"WHERE {' AND '.join(where)}" if where else ""

        rows = self._sql.execute_query_mappings(
            f"""
            SELECT
              sr.id,
              sr.parent_concept_id,
              sr.child_concept_id,
              sr.relationship_type,
              sr.created_at,
              sp.vertical,
              sp.vertical_norm,
              sp.concept_key AS parent_concept_key,
              sc.concept_key AS child_concept_key,
              (
                SELECT csp.name
                FROM semantic_concept csp
                WHERE UPPER(TRIM(csp.concept_key)) = UPPER(TRIM(sp.concept_key))
                  AND LOWER(COALESCE(csp.vertical_norm, 'generic')) IN (LOWER(COALESCE(sp.vertical_norm, 'generic')), 'generic')
                ORDER BY CASE WHEN LOWER(COALESCE(csp.vertical_norm, 'generic')) = LOWER(COALESCE(sp.vertical_norm, 'generic')) THEN 0 ELSE 1 END
                LIMIT 1
              ) AS parent_concept_name,
              (
                SELECT csc.name
                FROM semantic_concept csc
                WHERE UPPER(TRIM(csc.concept_key)) = UPPER(TRIM(sc.concept_key))
                  AND LOWER(COALESCE(csc.vertical_norm, 'generic')) IN (LOWER(COALESCE(sc.vertical_norm, 'generic')), 'generic')
                ORDER BY CASE WHEN LOWER(COALESCE(csc.vertical_norm, 'generic')) = LOWER(COALESCE(sc.vertical_norm, 'generic')) THEN 0 ELSE 1 END
                LIMIT 1
              ) AS child_concept_name
            FROM semantic_relationship sr
            JOIN semantic_registry sp ON sp.id = sr.parent_concept_id
            JOIN semantic_registry sc ON sc.id = sr.child_concept_id
            {where_sql}
            ORDER BY sr.id DESC
            LIMIT :limit OFFSET :offset
            """,
            params,
        )

        total_rows = self._sql.execute_query_mappings(
            f"""
            SELECT COUNT(*) AS total
            FROM semantic_relationship sr
            JOIN semantic_registry sp ON sp.id = sr.parent_concept_id
            JOIN semantic_registry sc ON sc.id = sr.child_concept_id
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

    def get_relationship(self, relationship_id: int) -> Dict[str, Any]:
        rel_id = _coerce_positive_int(relationship_id, field="id")
        rows = self._sql.execute_query_mappings(
            """
            SELECT
              sr.id,
              sr.parent_concept_id,
              sr.child_concept_id,
              sr.relationship_type,
              sr.created_at,
              sp.vertical,
              sp.vertical_norm,
              sp.concept_key AS parent_concept_key,
              sc.concept_key AS child_concept_key,
              (
                SELECT csp.name
                FROM semantic_concept csp
                WHERE UPPER(TRIM(csp.concept_key)) = UPPER(TRIM(sp.concept_key))
                  AND LOWER(COALESCE(csp.vertical_norm, 'generic')) IN (LOWER(COALESCE(sp.vertical_norm, 'generic')), 'generic')
                ORDER BY CASE WHEN LOWER(COALESCE(csp.vertical_norm, 'generic')) = LOWER(COALESCE(sp.vertical_norm, 'generic')) THEN 0 ELSE 1 END
                LIMIT 1
              ) AS parent_concept_name,
              (
                SELECT csc.name
                FROM semantic_concept csc
                WHERE UPPER(TRIM(csc.concept_key)) = UPPER(TRIM(sc.concept_key))
                  AND LOWER(COALESCE(csc.vertical_norm, 'generic')) IN (LOWER(COALESCE(sc.vertical_norm, 'generic')), 'generic')
                ORDER BY CASE WHEN LOWER(COALESCE(csc.vertical_norm, 'generic')) = LOWER(COALESCE(sc.vertical_norm, 'generic')) THEN 0 ELSE 1 END
                LIMIT 1
              ) AS child_concept_name
            FROM semantic_relationship sr
            JOIN semantic_registry sp ON sp.id = sr.parent_concept_id
            JOIN semantic_registry sc ON sc.id = sr.child_concept_id
            WHERE sr.id = :id
            LIMIT 1
            """,
            {"id": rel_id},
        )
        if not rows:
            raise ForgeError("semantic_relationship entry not found", status_code=404)
        return self._normalize_row(rows[0])

    def create_relationship(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(payload, dict):
            raise ForgeError("Invalid JSON body", status_code=400)

        parent_id = _coerce_positive_int(payload.get("parent_concept_id"), field="parent_concept_id")
        child_id = _coerce_positive_int(payload.get("child_concept_id"), field="child_concept_id")
        relation_type = str(payload.get("relationship_type") or "").strip().lower()

        if not relation_type:
            raise ForgeError("relationship_type is required", status_code=400)
        if len(relation_type) > 100:
            raise ForgeError("relationship_type exceeds 100 characters", status_code=400)
        if parent_id == child_id:
            raise ForgeError("parent_concept_id and child_concept_id must differ", status_code=400)

        self._assert_same_vertical(parent_id, child_id)

        if self._requires_cycle_guard(relation_type) and self._has_path(
            start_concept_id=child_id,
            target_concept_id=parent_id,
            relationship_types=_CYCLE_GUARD_RELATIONSHIP_TYPES,
        ):
            raise ForgeError("relationship would create a cycle", status_code=400)

        try:
            result = self._sql.execute_insert(
                """
                INSERT INTO semantic_relationship (
                  parent_concept_id,
                  child_concept_id,
                  relationship_type
                ) VALUES (
                  :parent_concept_id,
                  :child_concept_id,
                  :relationship_type
                )
                """,
                {
                    "parent_concept_id": parent_id,
                    "child_concept_id": child_id,
                    "relationship_type": relation_type,
                },
            )
        except SQLAlchemyError as exc:
            _raise_write_error(exc)

        if result.lastrowid:
            return self.get_relationship(int(result.lastrowid))
        raise ForgeError("Failed to create semantic_relationship entry", status_code=500)

    def delete_relationship(self, relationship_id: int) -> None:
        rel_id = _coerce_positive_int(relationship_id, field="id")
        affected = self._sql.execute_write(
            """
            DELETE FROM semantic_relationship
            WHERE id = :id
            """,
            {"id": rel_id},
        )
        if int(affected or 0) <= 0:
            raise ForgeError("semantic_relationship entry not found", status_code=404)

    def patch_relationship(self, relationship_id: int, payload: Dict[str, Any]) -> Dict[str, Any]:
        rel_id = _coerce_positive_int(relationship_id, field="id")
        if not isinstance(payload, dict):
            raise ForgeError("Invalid JSON body", status_code=400)

        current = self.get_relationship(rel_id)
        parent_id = int(current["parent_concept_id"])
        child_id = int(current["child_concept_id"])
        current_relation_type = str(current.get("relationship_type") or "").strip().lower()
        relation_type = current_relation_type

        if "parent_concept_id" in payload:
            parent_id = _coerce_positive_int(payload.get("parent_concept_id"), field="parent_concept_id")
        if "child_concept_id" in payload:
            child_id = _coerce_positive_int(payload.get("child_concept_id"), field="child_concept_id")
        if "relationship_type" in payload:
            relation_type = str(payload.get("relationship_type") or "").strip().lower()

        if parent_id == child_id:
            raise ForgeError("parent_concept_id and child_concept_id must differ", status_code=400)
        if not relation_type:
            raise ForgeError("relationship_type is required", status_code=400)
        if len(relation_type) > 100:
            raise ForgeError("relationship_type exceeds 100 characters", status_code=400)

        self._assert_same_vertical(parent_id, child_id)

        current_parent = int(current["parent_concept_id"])
        current_child = int(current["child_concept_id"])
        parent_or_child_changed = parent_id != current_parent or child_id != current_child
        relation_type_changed = relation_type != current_relation_type
        should_cycle_check = self._requires_cycle_guard(relation_type) and (
            parent_or_child_changed or relation_type_changed
        )
        if should_cycle_check and self._has_path(
            start_concept_id=child_id,
            target_concept_id=parent_id,
            exclude_relationship_id=rel_id,
            relationship_types=_CYCLE_GUARD_RELATIONSHIP_TYPES,
        ):
            raise ForgeError("relationship would create a cycle", status_code=400)

        try:
            affected = self._sql.execute_write(
                """
                UPDATE semantic_relationship
                SET parent_concept_id = :parent_concept_id,
                    child_concept_id = :child_concept_id,
                    relationship_type = :relationship_type
                WHERE id = :id
                """,
                {
                    "id": rel_id,
                    "parent_concept_id": parent_id,
                    "child_concept_id": child_id,
                    "relationship_type": relation_type,
                },
            )
        except SQLAlchemyError as exc:
            _raise_write_error(exc)
            affected = 0

        if int(affected or 0) <= 0:
            raise ForgeError("semantic_relationship entry not found", status_code=404)
        return self.get_relationship(rel_id)

    def get_children(self, concept_id: int, relationship_type: Optional[str] = None) -> list[Dict[str, Any]]:
        parent_id = _coerce_positive_int(concept_id, field="concept_id")
        params: Dict[str, Any] = {"concept_id": parent_id}
        where = ["sr.parent_concept_id = :concept_id"]
        if relationship_type is not None and str(relationship_type).strip() != "":
            where.append("LOWER(sr.relationship_type) = :relationship_type")
            params["relationship_type"] = str(relationship_type).strip().lower()

        rows = self._sql.execute_query_mappings(
            f"""
            SELECT
              sr.id,
              sr.parent_concept_id,
              sr.child_concept_id,
              sr.relationship_type,
              sr.created_at,
              sc.concept_key AS child_concept_key,
              (
                SELECT csc.name
                FROM semantic_concept csc
                WHERE UPPER(TRIM(csc.concept_key)) = UPPER(TRIM(sc.concept_key))
                  AND LOWER(COALESCE(csc.vertical_norm, 'generic')) IN (LOWER(COALESCE(sc.vertical_norm, 'generic')), 'generic')
                ORDER BY CASE WHEN LOWER(COALESCE(csc.vertical_norm, 'generic')) = LOWER(COALESCE(sc.vertical_norm, 'generic')) THEN 0 ELSE 1 END
                LIMIT 1
              ) AS child_concept_name,
              sc.vertical,
              sc.vertical_norm
            FROM semantic_relationship sr
            JOIN semantic_registry sc ON sc.id = sr.child_concept_id
            WHERE {' AND '.join(where)}
            ORDER BY sr.id DESC
            """,
            params,
        )
        return [self._normalize_row(row) for row in rows]

    def get_parents(self, concept_id: int, relationship_type: Optional[str] = None) -> list[Dict[str, Any]]:
        child_id = _coerce_positive_int(concept_id, field="concept_id")
        params: Dict[str, Any] = {"concept_id": child_id}
        where = ["sr.child_concept_id = :concept_id"]
        if relationship_type is not None and str(relationship_type).strip() != "":
            where.append("LOWER(sr.relationship_type) = :relationship_type")
            params["relationship_type"] = str(relationship_type).strip().lower()

        rows = self._sql.execute_query_mappings(
            f"""
            SELECT
              sr.id,
              sr.parent_concept_id,
              sr.child_concept_id,
              sr.relationship_type,
              sr.created_at,
              sp.concept_key AS parent_concept_key,
              (
                SELECT csp.name
                FROM semantic_concept csp
                WHERE UPPER(TRIM(csp.concept_key)) = UPPER(TRIM(sp.concept_key))
                  AND LOWER(COALESCE(csp.vertical_norm, 'generic')) IN (LOWER(COALESCE(sp.vertical_norm, 'generic')), 'generic')
                ORDER BY CASE WHEN LOWER(COALESCE(csp.vertical_norm, 'generic')) = LOWER(COALESCE(sp.vertical_norm, 'generic')) THEN 0 ELSE 1 END
                LIMIT 1
              ) AS parent_concept_name,
              sp.vertical,
              sp.vertical_norm
            FROM semantic_relationship sr
            JOIN semantic_registry sp ON sp.id = sr.parent_concept_id
            WHERE {' AND '.join(where)}
            ORDER BY sr.id DESC
            """,
            params,
        )
        return [self._normalize_row(row) for row in rows]

    def list_concept_lookup(
        self,
        *,
        vertical: Optional[str] = None,
        q: Optional[str] = None,
        page: int = 1,
        page_size: int = 100,
    ) -> Dict[str, Any]:
        page_val = max(1, int(page or 1))
        size_val = min(500, max(1, int(page_size or 100)))
        offset = (page_val - 1) * size_val

        where = []
        params: Dict[str, Any] = {"limit": size_val, "offset": offset}

        vertical_norm = _normalize_vertical(vertical)
        if vertical_norm is not None:
            where.append("sr.vertical_norm = :vertical_norm")
            params["vertical_norm"] = vertical_norm

        if q is not None and str(q).strip() != "":
            token = f"%{str(q).strip().lower()}%"
            where.append(
                "("
                "LOWER(sr.concept_key) LIKE :q "
                "OR LOWER(COALESCE(sr.description, '')) LIKE :q "
                "OR LOWER(COALESCE((SELECT scn.name FROM semantic_concept scn "
                "  WHERE UPPER(TRIM(scn.concept_key)) = UPPER(TRIM(sr.concept_key)) "
                "    AND LOWER(COALESCE(scn.vertical_norm, 'generic')) IN (LOWER(COALESCE(sr.vertical_norm, 'generic')), 'generic') "
                "  ORDER BY CASE WHEN LOWER(COALESCE(scn.vertical_norm, 'generic')) = LOWER(COALESCE(sr.vertical_norm, 'generic')) THEN 0 ELSE 1 END "
                "  LIMIT 1), '')) LIKE :q"
                ")"
            )
            params["q"] = token

        where_sql = f"WHERE {' AND '.join(where)}" if where else ""

        rows = self._sql.execute_query_mappings(
            f"""
            SELECT
              sr.id,
              sr.vertical_norm,
              sr.concept_key,
              sr.semantic_type,
              sr.description,
              (
                SELECT scn.name
                FROM semantic_concept scn
                WHERE UPPER(TRIM(scn.concept_key)) = UPPER(TRIM(sr.concept_key))
                  AND LOWER(COALESCE(scn.vertical_norm, 'generic')) IN (LOWER(COALESCE(sr.vertical_norm, 'generic')), 'generic')
                ORDER BY CASE WHEN LOWER(COALESCE(scn.vertical_norm, 'generic')) = LOWER(COALESCE(sr.vertical_norm, 'generic')) THEN 0 ELSE 1 END
                LIMIT 1
              ) AS concept_name
            FROM semantic_registry sr
            {where_sql}
            ORDER BY sr.concept_key ASC
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

        out_rows: list[Dict[str, Any]] = []
        for row in rows:
            entry = {
                "id": int(row.get("id") or 0),
                "vertical_norm": str(row.get("vertical_norm") or "").strip(),
                "concept_key": str(row.get("concept_key") or "").strip(),
                "semantic_type": str(row.get("semantic_type") or "").strip(),
            }
            concept_name = str(row.get("concept_name") or "").strip()
            if concept_name == "":
                concept_name = _humanize_concept_key(entry["concept_key"])
            entry["concept_name"] = concept_name
            entry["display_label"] = f"{concept_name} ({entry['concept_key']})"
            out_rows.append(entry)

        return {
            "rows": out_rows,
            "total": total,
            "page": page_val,
            "page_size": size_val,
        }

    def _assert_same_vertical(self, parent_id: int, child_id: int) -> None:
        rows = self._sql.execute_query_mappings(
            """
            SELECT id, vertical_norm
            FROM semantic_registry
            WHERE id = :parent_id OR id = :child_id
            """,
            {"parent_id": parent_id, "child_id": child_id},
        )

        if len(rows) != 2:
            raise ForgeError("parent_concept_id or child_concept_id not found", status_code=404)

        vertical_by_id = {int(row["id"]): str(row.get("vertical_norm") or "") for row in rows}
        if vertical_by_id.get(parent_id) != vertical_by_id.get(child_id):
            raise ForgeError("Cross-vertical relationships are not allowed", status_code=400)

    def _has_path(
        self,
        *,
        start_concept_id: int,
        target_concept_id: int,
        exclude_relationship_id: Optional[int] = None,
        relationship_types: Optional[set[str] | frozenset[str]] = None,
    ) -> bool:
        allowed_rel_types = {
            str(item or "").strip().lower() for item in (relationship_types or set()) if str(item or "").strip()
        }
        if relationship_types is not None and not allowed_rel_types:
            return False

        queue: deque[int] = deque([start_concept_id])
        visited: set[int] = set()

        while queue:
            current = queue.popleft()
            if current in visited:
                continue
            visited.add(current)

            if exclude_relationship_id is None:
                rows = self._sql.execute_query_mappings(
                    """
                    SELECT child_concept_id, relationship_type
                    FROM semantic_relationship
                    WHERE parent_concept_id = :concept_id
                    """,
                    {"concept_id": current},
                )
            else:
                rows = self._sql.execute_query_mappings(
                    """
                    SELECT child_concept_id, relationship_type
                    FROM semantic_relationship
                    WHERE parent_concept_id = :concept_id
                      AND id <> :exclude_relationship_id
                    """,
                    {
                        "concept_id": current,
                        "exclude_relationship_id": int(exclude_relationship_id),
                    },
                )

            for row in rows:
                row_rel_type = str(row.get("relationship_type") or "").strip().lower()
                if allowed_rel_types and row_rel_type not in allowed_rel_types:
                    continue
                child_id = int(row["child_concept_id"])
                if child_id == target_concept_id:
                    return True
                if child_id not in visited:
                    queue.append(child_id)

        return False

    @staticmethod
    def _requires_cycle_guard(relationship_type: str) -> bool:
        return str(relationship_type or "").strip().lower() in _CYCLE_GUARD_RELATIONSHIP_TYPES

    @staticmethod
    def _normalize_row(row: Dict[str, Any]) -> Dict[str, Any]:
        out = dict(row)
        for key in ("id", "parent_concept_id", "child_concept_id"):
            if key in out and out[key] is not None:
                out[key] = int(out[key])
        for key, value in list(out.items()):
            if isinstance(value, (datetime, date)):
                out[key] = value.isoformat()
        if "parent_concept_key" in out and "parent_concept_name" in out:
            parent_name = str(out.get("parent_concept_name") or "").strip()
            if parent_name == "":
                parent_name = _humanize_concept_key(str(out.get("parent_concept_key") or ""))
            out["parent_display_label"] = f"{parent_name} ({str(out.get('parent_concept_key') or '').strip()})"
        if "child_concept_key" in out and "child_concept_name" in out:
            child_name = str(out.get("child_concept_name") or "").strip()
            if child_name == "":
                child_name = _humanize_concept_key(str(out.get("child_concept_key") or ""))
            out["child_display_label"] = f"{child_name} ({str(out.get('child_concept_key') or '').strip()})"
        return out


def _raise_write_error(exc: Exception) -> None:
    msg = str(exc)
    if "Duplicate entry" in msg:
        raise ForgeError("Duplicate semantic_relationship entry", status_code=409) from exc
    raise ForgeError("semantic_relationship write failed", status_code=500, details={"message": msg}) from exc


def _humanize_concept_key(value: Any) -> str:
    raw = str(value or "").strip()
    if raw == "":
        return ""
    return " ".join(token.capitalize() for token in raw.replace("-", "_").split("_") if token)
