from __future__ import annotations

from typing import Any, Dict, Optional

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.exceptions.forge_error import ForgeError
from app.ports.sql_executor import ForgeQueryPort
from app.services.metadata.gateway import MetadataGateway

ALLOWED_COLUMN_FIELDS = {
    "dataType",
    "description",
    "isActive",
    "semanticType",
    "semanticEntity",
    "semanticSubType",
    "semanticSource",
    "semanticConfidence",
}

ALLOWED_TABLE_FIELDS = {
    "name",
    "sourceTableName",
    "description",
    "origin",
    "isMissingInSource",
}


class ModelUpdateService:
    def __init__(self, *, sql: Optional[ForgeQueryPort] = None, metadata_gateway: Optional[MetadataGateway] = None) -> None:
        self._sql = sql or ForgeMetaSQL()
        self._metadata_gateway = metadata_gateway or MetadataGateway(sql=self._sql)

    def patch_column(
        self,
        *,
        column_id: int,
        patch: Dict[str, Any],
        updated_by: Optional[str] = None,
    ) -> Dict[str, Any]:
        del updated_by
        bad = [k for k in patch.keys() if k not in ALLOWED_COLUMN_FIELDS]
        if bad:
            raise ForgeError(f"Invalid fields in patch: {', '.join(bad)}", status_code=400)

        sets = []
        params: Dict[str, Any] = {"id": int(column_id)}

        if "dataType" in patch:
            sets.append("c.data_type = :data_type")
            params["data_type"] = _clean_or_none(patch.get("dataType"), max_len=200)
        if "description" in patch:
            sets.append("c.description = :description")
            params["description"] = _clean_or_none(patch.get("description"), max_len=2000)
        if "isActive" in patch:
            sets.append("c.is_active = :is_active")
            params["is_active"] = 1 if bool(patch.get("isActive")) else 0
        if "semanticType" in patch:
            sets.append("c.semantic_type = :semantic_type")
            params["semantic_type"] = _clean_or_none(patch.get("semanticType"), max_len=100)
        if "semanticEntity" in patch:
            sets.append("c.semantic_entity = :semantic_entity")
            params["semantic_entity"] = _clean_or_none(patch.get("semanticEntity"), max_len=100)
        if "semanticSubType" in patch:
            sets.append("c.semantic_sub_type = :semantic_sub_type")
            params["semantic_sub_type"] = _clean_or_none(patch.get("semanticSubType"), max_len=200)
        if "semanticSource" in patch:
            sets.append("c.semantic_source = :semantic_source")
            params["semantic_source"] = _clean_or_none(patch.get("semanticSource"), max_len=20)
        if "semanticConfidence" in patch:
            sets.append("c.semantic_confidence = :semantic_confidence")
            params["semantic_confidence"] = _coerce_confidence(patch.get("semanticConfidence"))

        if not sets:
            raise ForgeError("Empty patch", status_code=400)

        upd_sql = f"""
UPDATE model_column c
SET {", ".join(sets)}
WHERE c.id = :id
"""
        affected = self._sql.execute_write(upd_sql, params)
        if affected == 0:
            raise ForgeError("Dictionary column not found", status_code=404)

        workspace_updates: Dict[str, Any] = {}
        if "data_type" in params:
            workspace_updates["data_type"] = params["data_type"]
        if "description" in params:
            workspace_updates["description"] = params["description"]
        if "is_active" in params:
            workspace_updates["is_active"] = params["is_active"]
        if "semantic_type" in params:
            workspace_updates["semantic_type"] = params["semantic_type"]
        if "semantic_entity" in params:
            workspace_updates["semantic_entity"] = params["semantic_entity"]
        if "semantic_sub_type" in params:
            workspace_updates["semantic_sub_type"] = params["semantic_sub_type"]
        if "semantic_source" in params:
            workspace_updates["semantic_source"] = params["semantic_source"]
        if "semantic_confidence" in params:
            workspace_updates["semantic_confidence"] = params["semantic_confidence"]
        if workspace_updates:
            self._metadata_gateway.sync_column_patch_from_model(
                model_column_id=int(column_id),
                updates=workspace_updates,
            )

        sel_sql = """
SELECT
  c.id,
  c.model_table_id,
  t.name AS table_name,
  c.column_name,
  c.data_type,
  c.description,
  c.semantic_type,
  c.semantic_entity,
  c.semantic_sub_type,
  c.semantic_source,
  c.semantic_confidence,
  c.is_active
FROM model_column c
JOIN model_table t ON t.id = c.model_table_id
WHERE c.id = :id
LIMIT 1
"""
        r = self._sql.execute_query(sel_sql, {"id": int(column_id)})
        if not r:
            raise ForgeError("Dictionary column not found", status_code=404)

        row = r[0]
        def _safe_idx(idx: int, default: Any = None) -> Any:
            try:
                return row[idx]
            except Exception:
                return default
        return {
            "id": int(_safe_idx(0, 0) or 0),
            "modelTableId": int(_safe_idx(1, 0) or 0),
            "tableName": str(_safe_idx(2, "") or ""),
            "columnName": str(_safe_idx(3, "") or ""),
            "dataType": _safe_idx(4),
            "description": _safe_idx(5),
            "semanticType": _safe_idx(6),
            "semanticEntity": _safe_idx(7),
            "semanticSubType": _safe_idx(8),
            "semanticSource": _safe_idx(9),
            "semanticConfidence": float(_safe_idx(10)) if _safe_idx(10) is not None else None,
            "isActive": bool(_safe_idx(11, 1)),
        }

    def create_column(
        self,
        *,
        table_name: str,
        column_name: str,
        data_type: Optional[str],
        description: Optional[str],
        is_active: bool,
        created_by: str,
    ) -> Dict[str, Any]:
        del created_by

        clean_table_name = _clean_or_none(table_name, max_len=255)
        clean_column_name = _clean_or_none(column_name, max_len=255)
        if not clean_table_name or not clean_column_name:
            raise ForgeError("tableName and columnName are required", status_code=400)

        sql_get_table = "SELECT id, name FROM model_table WHERE name = :name"
        sql_insert_table = (
            "INSERT INTO model_table(name, source_table_name, origin, is_missing_in_source, created_at) "
            "VALUES(:name, :source_table_name, :origin, 0, CURRENT_TIMESTAMP)"
        )
        sql_insert_col = """
INSERT INTO model_column(model_table_id, column_name, data_type, description, is_active)
VALUES(:mtid, :col, :dtype, :desc, :active)
"""
        sql_select_created = """
SELECT
  mc.id,
  mc.model_table_id AS modelTableId,
  mt.name AS tableName,
  mc.column_name AS columnName,
  mc.data_type AS dataType,
  mc.description AS description,
  mc.semantic_type AS semanticType,
  mc.semantic_entity AS semanticEntity,
  mc.semantic_sub_type AS semanticSubType,
  mc.semantic_source AS semanticSource,
  mc.semantic_confidence AS semanticConfidence,
  (mc.is_active = 1) AS isActive
FROM model_column mc
JOIN model_table mt ON mt.id = mc.model_table_id
WHERE mc.id = :id
"""

        with self._sql.transaction() as tx:
            mt_rows = tx.execute_query_mappings(sql_get_table, {"name": clean_table_name})
            mt = mt_rows[0] if mt_rows else None
            if not mt:
                res = tx.execute_insert(
                    sql_insert_table,
                    {
                        "name": clean_table_name,
                        "source_table_name": clean_table_name,
                        "origin": "MANUAL",
                    },
                )
                mtid = int(res.lastrowid)
            else:
                mtid = int(mt["id"])

            try:
                res = tx.execute_insert(
                    sql_insert_col,
                    {
                        "mtid": mtid,
                        "col": clean_column_name,
                        "dtype": _clean_or_none(data_type, max_len=200),
                        "desc": _clean_or_none(description, max_len=2000),
                        "active": 1 if is_active else 0,
                    },
                )
                new_id = int(res.lastrowid)
            except Exception as exc:
                raise ForgeError("Column already exists for this table", status_code=409) from exc

            created_rows = tx.execute_query_mappings(sql_select_created, {"id": new_id})
            created = created_rows[0] if created_rows else None

        if created:
            self._metadata_gateway.sync_column_patch_from_model(
                model_column_id=int(created.get("id") or 0),
                updates={
                    "data_type": created.get("dataType"),
                    "description": created.get("description"),
                    "is_active": 1 if bool(created.get("isActive")) else 0,
                },
            )
        return dict(created) if created else {}

    def delete_column(self, *, column_id: int) -> Dict[str, Any]:
        affected = self._sql.execute_write(
            "DELETE FROM model_column WHERE id = :id",
            {"id": int(column_id)},
        )
        if affected == 0:
            raise ForgeError("Dictionary column not found", status_code=404)
        self._metadata_gateway.clear_workspace_model_column_reference(model_column_id=int(column_id))
        return {"id": int(column_id), "deleted": True}

    def create_table(
        self,
        *,
        name: str,
        source_table_name: Optional[str] = None,
        description: Optional[str] = None,
        origin: Optional[str] = None,
    ) -> Dict[str, Any]:
        clean_name = _clean_or_none(name, max_len=255)
        if not clean_name:
            raise ForgeError("name is required", status_code=400)

        clean_source = _clean_or_none(source_table_name, max_len=255) or clean_name
        clean_desc = _clean_or_none(description, max_len=2000)
        clean_origin = (_clean_or_none(origin, max_len=16) or "MANUAL").upper()

        try:
            with self._sql.transaction() as tx:
                res = tx.execute_insert(
                    """
INSERT INTO model_table(name, source_table_name, description, origin, is_missing_in_source, created_at)
VALUES(:name, :source_table_name, :description, :origin, 0, CURRENT_TIMESTAMP)
""",
                    {
                        "name": clean_name,
                        "source_table_name": clean_source,
                        "description": clean_desc,
                        "origin": clean_origin,
                    },
                )
                new_id = int(res.lastrowid)
                rows = tx.execute_query_mappings(
                    """
SELECT id, name, source_table_name, description, origin, is_missing_in_source
FROM model_table
WHERE id = :id
LIMIT 1
""",
                    {"id": new_id},
                )
        except Exception as exc:
            raise ForgeError("Table already exists", status_code=409) from exc

        if not rows:
            raise ForgeError("Table create failed", status_code=500)
        mapped = _map_table_row(rows[0])
        self._metadata_gateway.sync_table_patch_from_model(
            model_table_id=int(mapped["id"]),
            updates={
                "qf_table_name": mapped["name"],
                "source_table_name": mapped.get("sourceTableName"),
                "description": mapped.get("description"),
                "origin": mapped.get("origin"),
                "is_missing_in_source": 1 if bool(mapped.get("isMissingInSource")) else 0,
            },
        )
        return mapped

    def patch_table(
        self,
        *,
        table_id: int,
        patch: Dict[str, Any],
    ) -> Dict[str, Any]:
        bad = [k for k in patch.keys() if k not in ALLOWED_TABLE_FIELDS]
        if bad:
            raise ForgeError(f"Invalid fields in patch: {', '.join(bad)}", status_code=400)

        sets = []
        params: Dict[str, Any] = {"id": int(table_id)}

        if "name" in patch:
            val = _clean_or_none(patch.get("name"), max_len=255)
            if not val:
                raise ForgeError("name cannot be empty", status_code=400)
            sets.append("name = :name")
            params["name"] = val
        if "sourceTableName" in patch:
            sets.append("source_table_name = :source_table_name")
            params["source_table_name"] = _clean_or_none(patch.get("sourceTableName"), max_len=255)
        if "description" in patch:
            sets.append("description = :description")
            params["description"] = _clean_or_none(patch.get("description"), max_len=2000)
        if "origin" in patch:
            val = _clean_or_none(patch.get("origin"), max_len=16)
            sets.append("origin = :origin")
            params["origin"] = val.upper() if val else None
        if "isMissingInSource" in patch:
            sets.append("is_missing_in_source = :is_missing_in_source")
            params["is_missing_in_source"] = 1 if bool(patch.get("isMissingInSource")) else 0

        if not sets:
            raise ForgeError("Empty patch", status_code=400)

        try:
            affected = self._sql.execute_write(
                f"""
UPDATE model_table
SET {", ".join(sets)}
WHERE id = :id
""",
                params,
            )
        except Exception as exc:
            raise ForgeError("Table update failed", status_code=409) from exc
        if affected == 0:
            raise ForgeError("Table not found", status_code=404)

        workspace_updates: Dict[str, Any] = {}
        if "name" in params:
            workspace_updates["qf_table_name"] = params["name"]
        if "source_table_name" in params:
            workspace_updates["source_table_name"] = params["source_table_name"]
        if "description" in params:
            workspace_updates["description"] = params["description"]
        if "origin" in params:
            workspace_updates["origin"] = params["origin"]
        if "is_missing_in_source" in params:
            workspace_updates["is_missing_in_source"] = params["is_missing_in_source"]
        if workspace_updates:
            self._metadata_gateway.sync_table_patch_from_model(
                model_table_id=int(table_id),
                updates=workspace_updates,
            )

        rows = self._sql.execute_query_mappings(
            """
SELECT id, name, source_table_name, description, origin, is_missing_in_source
FROM model_table
WHERE id = :id
LIMIT 1
""",
            {"id": int(table_id)},
        )
        if not rows:
            raise ForgeError("Table not found", status_code=404)
        return _map_table_row(rows[0])

    def delete_table(self, *, table_id: int) -> Dict[str, Any]:
        try:
            affected = self._sql.execute_write(
                "DELETE FROM model_table WHERE id = :id",
                {"id": int(table_id)},
            )
        except Exception as exc:
            raise ForgeError(
                "Table is referenced and cannot be deleted",
                status_code=409,
            ) from exc
        if affected == 0:
            raise ForgeError("Table not found", status_code=404)
        self._metadata_gateway.clear_workspace_model_table_reference(model_table_id=int(table_id))
        return {"id": int(table_id), "deleted": True}


def _clean_or_none(value: Any, *, max_len: int) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    if text == "":
        return None
    return text[:max_len]


def _coerce_confidence(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        parsed = float(value)
    except Exception:
        raise ForgeError("semanticConfidence must be numeric", status_code=400)
    if parsed < 0.0 or parsed > 1.0:
        raise ForgeError("semanticConfidence must be between 0 and 1", status_code=400)
    return parsed


def _map_table_row(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": int(row["id"]),
        "name": str(row.get("name") or ""),
        "sourceTableName": row.get("source_table_name"),
        "description": row.get("description"),
        "origin": str(row.get("origin") or ""),
        "isMissingInSource": bool(row.get("is_missing_in_source")),
    }
