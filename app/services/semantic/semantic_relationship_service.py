from __future__ import annotations

from collections import deque
from typing import Any, Dict, Optional

from app.adapters.mysql_sql_executor import MySQLSQLExecutor
from app.exceptions.service_error import ServiceError
from app.ports.sql_executor import SQLExecutor
from app.services.semantic.semantic_registry_service import _coerce_positive_int, _normalize_vertical


class SemanticRelationshipService:
    def __init__(self, *, sql: Optional[SQLExecutor] = None) -> None:
        self._sql = sql or MySQLSQLExecutor()

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
              sc.concept_key AS child_concept_key
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
              sc.concept_key AS child_concept_key
            FROM semantic_relationship sr
            JOIN semantic_registry sp ON sp.id = sr.parent_concept_id
            JOIN semantic_registry sc ON sc.id = sr.child_concept_id
            WHERE sr.id = :id
            LIMIT 1
            """,
            {"id": rel_id},
        )
        if not rows:
            raise ServiceError("semantic_relationship entry not found", status_code=404)
        return self._normalize_row(rows[0])

    def create_relationship(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(payload, dict):
            raise ServiceError("Invalid JSON body", status_code=400)

        parent_id = _coerce_positive_int(payload.get("parent_concept_id"), field="parent_concept_id")
        child_id = _coerce_positive_int(payload.get("child_concept_id"), field="child_concept_id")
        relation_type = str(payload.get("relationship_type") or "").strip().lower()

        if not relation_type:
            raise ServiceError("relationship_type is required", status_code=400)
        if len(relation_type) > 100:
            raise ServiceError("relationship_type exceeds 100 characters", status_code=400)
        if parent_id == child_id:
            raise ServiceError("parent_concept_id and child_concept_id must differ", status_code=400)

        self._assert_same_vertical(parent_id, child_id)

        if self._has_path(start_concept_id=child_id, target_concept_id=parent_id):
            raise ServiceError("relationship would create a cycle", status_code=400)

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
        except Exception as exc:
            _raise_write_error(exc)

        if result.lastrowid:
            return self.get_relationship(int(result.lastrowid))
        raise ServiceError("Failed to create semantic_relationship entry", status_code=500)

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
            raise ServiceError("semantic_relationship entry not found", status_code=404)

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
            raise ServiceError("parent_concept_id or child_concept_id not found", status_code=404)

        vertical_by_id = {int(row["id"]): str(row.get("vertical_norm") or "") for row in rows}
        if vertical_by_id.get(parent_id) != vertical_by_id.get(child_id):
            raise ServiceError("Cross-vertical relationships are not allowed", status_code=400)

    def _has_path(self, *, start_concept_id: int, target_concept_id: int) -> bool:
        queue: deque[int] = deque([start_concept_id])
        visited: set[int] = set()

        while queue:
            current = queue.popleft()
            if current in visited:
                continue
            visited.add(current)

            rows = self._sql.execute_query_mappings(
                """
                SELECT child_concept_id
                FROM semantic_relationship
                WHERE parent_concept_id = :concept_id
                """,
                {"concept_id": current},
            )

            for row in rows:
                child_id = int(row["child_concept_id"])
                if child_id == target_concept_id:
                    return True
                if child_id not in visited:
                    queue.append(child_id)

        return False

    @staticmethod
    def _normalize_row(row: Dict[str, Any]) -> Dict[str, Any]:
        out = dict(row)
        for key in ("id", "parent_concept_id", "child_concept_id"):
            if key in out and out[key] is not None:
                out[key] = int(out[key])
        return out


def _raise_write_error(exc: Exception) -> None:
    msg = str(exc)
    if "Duplicate entry" in msg:
        raise ServiceError("Duplicate semantic_relationship entry", status_code=409) from exc
    raise ServiceError("semantic_relationship write failed", status_code=500, details={"message": msg}) from exc
