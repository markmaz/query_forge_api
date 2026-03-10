from __future__ import annotations

from typing import Any, Dict, Optional

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.config import METADATA_SOURCE_MODE
from app.exceptions.forge_error import ForgeError
from app.ports.sql_executor import ForgeQueryPort
from app.services.semantic.semantic_registry_service import _coerce_positive_int, _normalize_vertical


class SemanticMappingService:
    def __init__(self, *, sql: Optional[ForgeQueryPort] = None, metadata_mode: Optional[str] = None) -> None:
        self._sql = sql or ForgeMetaSQL()
        self._metadata_mode = str(metadata_mode or METADATA_SOURCE_MODE or "legacy").strip().lower() or "legacy"

    def list_mappings(
        self,
        *,
        vertical: Optional[str] = None,
        workspace_id: Optional[str] = None,
        concept_key: Optional[str] = None,
        model_column_id: Optional[int] = None,
        workspace_column_id: Optional[int] = None,
        table_name: Optional[str] = None,
        column_name: Optional[str] = None,
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

        workspace_norm = _normalize_workspace(workspace_id)
        if workspace_norm is not None:
            where.append("scm.workspace_norm = :workspace_norm")
            params["workspace_norm"] = workspace_norm

        if concept_key is not None and str(concept_key).strip() != "":
            where.append("LOWER(sr.concept_key) = :concept_key")
            params["concept_key"] = str(concept_key).strip().lower()

        if workspace_column_id is not None:
            resolved = self._resolve_workspace_column(_coerce_positive_int(workspace_column_id, field="workspace_column_id"))
            if resolved is None:
                return {"rows": [], "total": 0, "page": page_val, "page_size": size_val}
            where.append("scm.model_column_id = :model_column_id")
            params["model_column_id"] = int(resolved["model_column_id"])

        if model_column_id is not None:
            where.append("scm.model_column_id = :model_column_id")
            params["model_column_id"] = _coerce_positive_int(model_column_id, field="model_column_id")

        if table_name is not None and str(table_name).strip() != "":
            where.append("LOWER(COALESCE(scm.table_name, '')) = :table_name")
            params["table_name"] = str(table_name).strip().lower()

        if column_name is not None and str(column_name).strip() != "":
            where.append("LOWER(COALESCE(scm.column_name, '')) = :column_name")
            params["column_name"] = str(column_name).strip().lower()

        where_sql = f"WHERE {' AND '.join(where)}" if where else ""

        rows = self._sql.execute_query_mappings(
            f"""
            SELECT
              scm.id,
              scm.semantic_registry_id,
              scm.workspace_id,
              scm.workspace_norm,
              scm.model_column_id,
              wc.id AS workspace_column_id,
              scm.table_name,
              scm.column_name,
              scm.priority_rank,
              scm.confidence_score,
              scm.created_at,
              sr.concept_key,
              sr.vertical,
              sr.vertical_norm,
              sr.semantic_type,
              sr.entity
            FROM semantic_column_map scm
            JOIN semantic_registry sr ON sr.id = scm.semantic_registry_id
            LEFT JOIN workspace_column wc ON wc.model_column_id = scm.model_column_id
            {where_sql}
            ORDER BY scm.priority_rank DESC, scm.confidence_score DESC, scm.id DESC
            LIMIT :limit OFFSET :offset
            """,
            params,
        )

        total_rows = self._sql.execute_query_mappings(
            f"""
            SELECT COUNT(*) AS total
            FROM semantic_column_map scm
            JOIN semantic_registry sr ON sr.id = scm.semantic_registry_id
            LEFT JOIN workspace_column wc ON wc.model_column_id = scm.model_column_id
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

    def get_mapping(self, mapping_id: int) -> Dict[str, Any]:
        row_id = _coerce_positive_int(mapping_id, field="id")
        rows = self._sql.execute_query_mappings(
            """
            SELECT
              scm.id,
              scm.semantic_registry_id,
              scm.workspace_id,
              scm.workspace_norm,
              scm.model_column_id,
              wc.id AS workspace_column_id,
              scm.table_name,
              scm.column_name,
              scm.priority_rank,
              scm.confidence_score,
              scm.created_at,
              sr.concept_key,
              sr.vertical,
              sr.vertical_norm,
              sr.semantic_type,
              sr.entity
            FROM semantic_column_map scm
            JOIN semantic_registry sr ON sr.id = scm.semantic_registry_id
            LEFT JOIN workspace_column wc ON wc.model_column_id = scm.model_column_id
            WHERE scm.id = :id
            LIMIT 1
            """,
            {"id": row_id},
        )
        if not rows:
            raise ForgeError("semantic_column_map entry not found", status_code=404)
        return self._normalize_row(rows[0])

    def create_mapping(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        data = self._normalize_payload(payload)
        self._assert_registry_exists(data["semantic_registry_id"])

        try:
            result = self._sql.execute_insert(
                """
                INSERT INTO semantic_column_map (
                  semantic_registry_id,
                  workspace_id,
                  model_column_id,
                  table_name,
                  column_name,
                  priority_rank,
                  confidence_score
                ) VALUES (
                  :semantic_registry_id,
                  :workspace_id,
                  :model_column_id,
                  :table_name,
                  :column_name,
                  :priority_rank,
                  :confidence_score
                )
                """,
                data,
            )
        except Exception as exc:
            _raise_write_error(exc)

        if result.lastrowid:
            return self.get_mapping(int(result.lastrowid))
        raise ForgeError("Failed to create semantic_column_map entry", status_code=500)

    def delete_mapping(self, mapping_id: int) -> None:
        row_id = _coerce_positive_int(mapping_id, field="id")
        affected = self._sql.execute_write(
            """
            DELETE FROM semantic_column_map
            WHERE id = :id
            """,
            {"id": row_id},
        )
        if int(affected or 0) <= 0:
            raise ForgeError("semantic_column_map entry not found", status_code=404)

    def resolve_best_column_for_concept(
        self,
        concept_key: str,
        vertical: Optional[str],
        workspace_id: Optional[str],
    ) -> Optional[Dict[str, Any]]:
        key = str(concept_key or "").strip().lower()
        if not key:
            raise ForgeError("concept_key is required", status_code=400)

        vertical_norm = _normalize_vertical(vertical) or "__global__"
        workspace_norm = _normalize_workspace(workspace_id) or "__global__"

        params: Dict[str, Any] = {
            "concept_key": key,
            "vertical_norm": vertical_norm,
            "workspace_norm": workspace_norm,
        }

        rows = self._sql.execute_query_mappings(
            """
            SELECT
              scm.id,
              scm.semantic_registry_id,
              scm.workspace_id,
              scm.workspace_norm,
              scm.model_column_id,
              scm.table_name,
              scm.column_name,
              scm.priority_rank,
              scm.confidence_score,
              scm.created_at,
              sr.concept_key,
              sr.vertical,
              sr.vertical_norm,
              sr.semantic_type,
              sr.entity
            FROM semantic_column_map scm
            JOIN semantic_registry sr ON sr.id = scm.semantic_registry_id
            WHERE LOWER(sr.concept_key) = :concept_key
              AND sr.vertical_norm = :vertical_norm
              AND scm.workspace_norm IN (:workspace_norm, '__global__')
            """,
            params,
        )

        if not rows:
            return None

        normalized = [self._normalize_row(row) for row in rows]
        normalized.sort(
            key=lambda row: (
                1 if row.get("workspace_norm") == workspace_norm else 0,
                int(row.get("priority_rank") or 0),
                float(row.get("confidence_score") or 0.0),
                int(row.get("id") or 0),
            ),
            reverse=True,
        )
        return normalized[0]

    def find_concepts_for_column(
        self,
        *,
        workspace_id: Optional[str],
        model_column_id: Optional[int] = None,
        workspace_column_id: Optional[int] = None,
        table_name: Optional[str] = None,
        column_name: Optional[str] = None,
    ) -> list[Dict[str, Any]]:
        workspace_norm = _normalize_workspace(workspace_id) or "__global__"

        where = ["scm.workspace_norm IN (:workspace_norm, '__global__')"]
        params: Dict[str, Any] = {"workspace_norm": workspace_norm}

        resolved_workspace: Optional[Dict[str, Any]] = None
        if workspace_column_id is not None:
            resolved_workspace = self._resolve_workspace_column(
                _coerce_positive_int(workspace_column_id, field="workspace_column_id")
            )
            if resolved_workspace is None:
                return []
            model_column_id = int(resolved_workspace["model_column_id"])

        has_model = model_column_id is not None
        has_table_col = bool(str(table_name or "").strip()) and bool(str(column_name or "").strip())

        if not has_model and not has_table_col:
            raise ForgeError(
                "model_column_id or table_name+column_name is required (workspace_column_id is also accepted)",
                status_code=400,
            )

        if has_model:
            where.append("scm.model_column_id = :model_column_id")
            params["model_column_id"] = _coerce_positive_int(model_column_id, field="model_column_id")
        else:
            where.append("LOWER(COALESCE(scm.table_name, '')) = :table_name")
            where.append("LOWER(COALESCE(scm.column_name, '')) = :column_name")
            params["table_name"] = str(table_name).strip().lower()
            params["column_name"] = str(column_name).strip().lower()

        rows = self._sql.execute_query_mappings(
            f"""
            SELECT
              scm.id,
              scm.semantic_registry_id,
              scm.workspace_id,
              scm.workspace_norm,
              scm.model_column_id,
              wc.id AS workspace_column_id,
              scm.table_name,
              scm.column_name,
              scm.priority_rank,
              scm.confidence_score,
              scm.created_at,
              sr.concept_key,
              sr.vertical,
              sr.vertical_norm,
              sr.semantic_type,
              sr.entity
            FROM semantic_column_map scm
            JOIN semantic_registry sr ON sr.id = scm.semantic_registry_id
            LEFT JOIN workspace_column wc ON wc.model_column_id = scm.model_column_id
            WHERE {' AND '.join(where)}
            ORDER BY scm.priority_rank DESC, scm.confidence_score DESC, scm.id DESC
            """,
            params,
        )

        return [self._normalize_row(row) for row in rows]

    def _normalize_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(payload, dict):
            raise ForgeError("Invalid JSON body", status_code=400)

        if "semantic_registry_id" not in payload:
            raise ForgeError("semantic_registry_id is required", status_code=400)

        semantic_registry_id = _coerce_positive_int(payload.get("semantic_registry_id"), field="semantic_registry_id")

        workspace_id = payload.get("workspace_id")
        if workspace_id is not None:
            workspace_id = str(workspace_id).strip() or None
            if workspace_id is not None and len(workspace_id) > 100:
                raise ForgeError("workspace_id exceeds 100 characters", status_code=400)

        model_column_id_raw = payload.get("model_column_id")
        model_column_id = None
        if model_column_id_raw not in (None, ""):
            model_column_id = _coerce_positive_int(model_column_id_raw, field="model_column_id")

        workspace_column_id_raw = payload.get("workspace_column_id")
        workspace_column_id = None
        if workspace_column_id_raw not in (None, ""):
            workspace_column_id = _coerce_positive_int(workspace_column_id_raw, field="workspace_column_id")

        table_name = payload.get("table_name")
        column_name = payload.get("column_name")
        table_name = str(table_name).strip() if table_name is not None else None
        column_name = str(column_name).strip() if column_name is not None else None
        table_name = table_name or None
        column_name = column_name or None

        if table_name is not None and len(table_name) > 200:
            raise ForgeError("table_name exceeds 200 characters", status_code=400)
        if column_name is not None and len(column_name) > 200:
            raise ForgeError("column_name exceeds 200 characters", status_code=400)

        has_model = model_column_id is not None or workspace_column_id is not None
        has_table_col = table_name is not None and column_name is not None

        if not has_model and not has_table_col:
            raise ForgeError(
                "mapping requires model_column_id or table_name+column_name (workspace_column_id is also accepted)",
                status_code=400,
            )

        if workspace_column_id is not None:
            resolved = self._resolve_workspace_column(workspace_column_id)
            if resolved is None:
                raise ForgeError("workspace_column_id not found", status_code=404)
            model_column_id = int(resolved["model_column_id"])
            table_name = table_name or str(resolved.get("table_name") or "").strip() or None
            column_name = column_name or str(resolved.get("column_name") or "").strip() or None
            if workspace_id is None:
                resolved_ws = str(resolved.get("workspace_id") or "").strip() or None
                workspace_id = resolved_ws

        if has_model:
            table_name = None
            column_name = None

        priority_rank = int(payload.get("priority_rank") or 0)

        confidence_score = payload.get("confidence_score")
        if confidence_score in (None, ""):
            confidence_score = None
        else:
            try:
                confidence_score = float(confidence_score)
            except Exception as exc:
                raise ForgeError("confidence_score must be numeric", status_code=400) from exc
            if confidence_score < 0.0 or confidence_score > 1.0:
                raise ForgeError("confidence_score must be between 0 and 1", status_code=400)

        return {
            "semantic_registry_id": semantic_registry_id,
            "workspace_id": workspace_id,
            "model_column_id": model_column_id,
            "workspace_column_id": workspace_column_id,
            "table_name": table_name,
            "column_name": column_name,
            "priority_rank": priority_rank,
            "confidence_score": confidence_score,
        }

    def _assert_registry_exists(self, semantic_registry_id: int) -> None:
        rows = self._sql.execute_query_mappings(
            """
            SELECT id
            FROM semantic_registry
            WHERE id = :id
            LIMIT 1
            """,
            {"id": semantic_registry_id},
        )
        if not rows:
            raise ForgeError("semantic_registry entry not found", status_code=404)

    @staticmethod
    def _normalize_row(row: Dict[str, Any]) -> Dict[str, Any]:
        out = dict(row)
        for key in ("id", "semantic_registry_id", "model_column_id", "workspace_column_id", "priority_rank"):
            if key in out and out[key] is not None:
                out[key] = int(out[key])
        if "confidence_score" in out and out["confidence_score"] is not None:
            out["confidence_score"] = float(out["confidence_score"])
        return out

    def _resolve_workspace_column(self, workspace_column_id: int) -> Optional[Dict[str, Any]]:
        rows = self._sql.execute_query_mappings(
            """
            SELECT
              wc.id AS workspace_column_id,
              COALESCE(wc.model_column_id, wc.id) AS model_column_id,
              wc.column_name,
              wt.workspace_id,
              COALESCE(NULLIF(wt.qf_table_name, ''), wt.table_name) AS table_name
            FROM workspace_column wc
            JOIN workspace_table wt
              ON wt.id = wc.workspace_table_id
            WHERE wc.id = :id
            LIMIT 1
            """,
            {"id": int(workspace_column_id)},
        )
        if not rows:
            return None
        row = rows[0]
        model_column_id = row.get("model_column_id")
        if model_column_id is None:
            return None
        return {
            "workspace_column_id": int(row["workspace_column_id"]),
            "model_column_id": int(model_column_id),
            "column_name": row.get("column_name"),
            "workspace_id": row.get("workspace_id"),
            "table_name": row.get("table_name"),
        }


def _normalize_workspace(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    if text == "":
        return None
    if text.lower() in {"global", "__global__", "null"}:
        return "__global__"
    return text


def _raise_write_error(exc: Exception) -> None:
    msg = str(exc)
    if "Duplicate entry" in msg:
        raise ForgeError("Duplicate semantic_column_map entry", status_code=409) from exc
    raise ForgeError("semantic_column_map write failed", status_code=500, details={"message": msg}) from exc
