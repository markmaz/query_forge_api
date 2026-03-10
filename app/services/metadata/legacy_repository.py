from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.exceptions.forge_error import ForgeError
from app.ports.sql_executor import ForgeQueryPort
from app.services.metadata.types import MetadataColumnRecord, MetadataTableRecord


def _chunk(xs: Sequence[Any], n: int = 500) -> List[Sequence[Any]]:
    return [xs[i : i + n] for i in range(0, len(xs), n)]


class LegacyMetadataRepository:
    """Metadata repository backed by model_table/model_column (current production source)."""

    def __init__(self, *, sql: Optional[ForgeQueryPort] = None) -> None:
        self._sql = sql or ForgeMetaSQL()

    def get_table_by_name(self, *, table_name: str) -> Optional[MetadataTableRecord]:
        name = str(table_name or "").strip()
        if not name:
            raise ForgeError("table_name is required", status_code=400)
        rows = self._sql.execute_query_mappings(
            """
            SELECT id, name, source_table_name, description, origin, is_missing_in_source
            FROM model_table
            WHERE name = :name
            LIMIT 1
            """,
            {"name": name},
        )
        if not rows:
            return None
        return _to_table_record(rows[0])

    def get_table_by_id(self, *, table_id: int) -> Optional[MetadataTableRecord]:
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
            return None
        return _to_table_record(rows[0])

    def list_tables(
        self,
        *,
        q: Optional[str] = None,
        limit: int = 500,
        offset: int = 0,
    ) -> List[MetadataTableRecord]:
        rows = self._sql.execute_query_mappings(
            """
            SELECT id, name, source_table_name, description, origin, is_missing_in_source
            FROM model_table
            WHERE (:q IS NULL OR name LIKE CONCAT('%', :q, '%'))
            ORDER BY name
            LIMIT :limit OFFSET :offset
            """,
            {
                "q": str(q or "").strip() or None,
                "limit": int(limit),
                "offset": int(offset),
            },
        )
        return [_to_table_record(row) for row in rows]

    def upsert_tables(
        self,
        *,
        tables: Sequence[Mapping[str, Any]],
        origin: str,
        overwrite_descriptions: bool = False,
    ) -> Dict[str, Any]:
        if not tables:
            return {"tables_upserted": 0, "name_to_id": {}}

        payload = []
        for table in tables:
            table_name = str(table.get("table_name") or "").strip()
            if not table_name:
                continue
            payload.append(
                {
                    "name": table_name,
                    "source_table_name": str(table.get("source_table_name") or table_name).strip(),
                    "description": _clean_or_none(table.get("description") or table.get("comment")),
                    "origin": str(origin or "MANUAL").upper(),
                }
            )

        if not payload:
            return {"tables_upserted": 0, "name_to_id": {}}

        desc_update = (
            "description = COALESCE(description, VALUES(description)),"
            if not overwrite_descriptions
            else "description = VALUES(description),"
        )

        with self._sql.transaction() as tx:
            for batch in _chunk(payload, 500):
                tx.execute_write(
                    f"""
                    INSERT INTO model_table (name, source_table_name, description, origin, is_missing_in_source, created_at)
                    VALUES (:name, :source_table_name, :description, :origin, 0, CURRENT_TIMESTAMP)
                    ON DUPLICATE KEY UPDATE
                      source_table_name = VALUES(source_table_name),
                      {desc_update}
                      origin = VALUES(origin),
                      is_missing_in_source = 0,
                      updated_at = CURRENT_TIMESTAMP
                    """,
                    list(batch),
                )

            names = sorted({item["name"] for item in payload})
            name_to_id: Dict[str, int] = {}
            for batch in _chunk(names, 500):
                placeholders = ", ".join(f":n{i}" for i in range(len(batch)))
                params = {f"n{i}": name for i, name in enumerate(batch)}
                rows = tx.execute_query_mappings(
                    f"SELECT id, name FROM model_table WHERE name IN ({placeholders})",
                    params,
                )
                for row in rows:
                    name_to_id[str(row.get("name") or "")] = int(row.get("id") or 0)

        return {"tables_upserted": len(payload), "name_to_id": name_to_id}

    def mark_tables_missing(self, *, seen_names: Iterable[str], origin: str) -> int:
        names = sorted({str(name or "").strip() for name in seen_names if str(name or "").strip()})
        if not names:
            return 0

        total = 0
        with self._sql.transaction() as tx:
            for batch in _chunk(names, 500):
                placeholders = ", ".join(f":n{i}" for i in range(len(batch)))
                params = {
                    "origin": str(origin or "MANUAL").upper(),
                    **{f"n{i}": name for i, name in enumerate(batch)},
                }
                total += int(
                    tx.execute_write(
                        f"""
                        UPDATE model_table
                        SET is_missing_in_source = 1,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE origin = :origin
                          AND is_missing_in_source = 0
                          AND name NOT IN ({placeholders})
                        """,
                        params,
                    )
                    or 0
                )
        return total

    def get_column_by_name(self, *, table_id: int, column_name: str) -> Optional[MetadataColumnRecord]:
        col = str(column_name or "").strip()
        if not col:
            raise ForgeError("column_name is required", status_code=400)

        rows = self._sql.execute_query_mappings(
            """
            SELECT
              id,
              model_table_id,
              column_name,
              data_type,
              description,
              is_active,
              origin,
              is_missing_in_source,
              semantic_type,
              semantic_entity,
              semantic_sub_type,
              semantic_source,
              semantic_confidence,
              semantic_concept_key
            FROM model_column
            WHERE model_table_id = :table_id
              AND column_name = :column_name
            LIMIT 1
            """,
            {"table_id": int(table_id), "column_name": col},
        )
        if not rows:
            return None
        return _to_column_record(rows[0])

    def upsert_columns(
        self,
        *,
        table_id_by_name: Mapping[str, int],
        columns: Sequence[Mapping[str, Any]],
        origin: str,
        overwrite_descriptions: bool = False,
    ) -> Dict[str, Any]:
        if not columns:
            return {"columns_upserted": 0, "cols_by_table_id": {}}

        payload: List[Dict[str, Any]] = []
        cols_by_table_id: Dict[int, set[str]] = {}

        for col in columns:
            table_name = str(col.get("table_name") or "").strip()
            table_id = int(table_id_by_name.get(table_name) or 0)
            if table_id <= 0:
                continue

            column_name = str(col.get("column_name") or "").strip()
            if not column_name:
                continue

            cols_by_table_id.setdefault(table_id, set()).add(column_name)

            payload.append(
                {
                    "model_table_id": table_id,
                    "column_name": column_name,
                    "data_type": _clean_or_none(col.get("data_type")),
                    "ordinal_position": int(col.get("ordinal_position") or 0),
                    "nullable": 1 if bool(col.get("is_nullable", True)) else 0,
                    "description": _clean_or_none(col.get("description") or col.get("comment")),
                    "origin": str(origin or "MANUAL").upper(),
                }
            )

        if not payload:
            return {"columns_upserted": 0, "cols_by_table_id": cols_by_table_id}

        desc_update = (
            "description = COALESCE(description, VALUES(description)),"
            if not overwrite_descriptions
            else "description = VALUES(description),"
        )

        with self._sql.transaction() as tx:
            for batch in _chunk(payload, 2000):
                tx.execute_write(
                    f"""
                    INSERT INTO model_column
                      (model_table_id, column_name, data_type, ordinal_position, nullable,
                       description, is_active, origin, is_missing_in_source, created_at)
                    VALUES
                      (:model_table_id, :column_name, :data_type, :ordinal_position, :nullable,
                       :description, 1, :origin, 0, CURRENT_TIMESTAMP)
                    ON DUPLICATE KEY UPDATE
                      data_type = VALUES(data_type),
                      ordinal_position = VALUES(ordinal_position),
                      nullable = VALUES(nullable),
                      {desc_update}
                      is_active = 1,
                      origin = VALUES(origin),
                      is_missing_in_source = 0,
                      updated_at = CURRENT_TIMESTAMP
                    """,
                    list(batch),
                )

        return {
            "columns_upserted": len(payload),
            "cols_by_table_id": {key: sorted(value) for key, value in cols_by_table_id.items()},
        }

    def mark_columns_missing(self, *, cols_by_table_id: Mapping[int, Iterable[str]], origin: str) -> int:
        total = 0
        with self._sql.transaction() as tx:
            for table_id, columns in cols_by_table_id.items():
                names = sorted({str(c or "").strip() for c in columns if str(c or "").strip()})
                if not names:
                    continue
                placeholders = ", ".join(f":c{i}" for i in range(len(names)))
                params = {
                    "table_id": int(table_id),
                    "origin": str(origin or "MANUAL").upper(),
                    **{f"c{i}": name for i, name in enumerate(names)},
                }
                total += int(
                    tx.execute_write(
                        f"""
                        UPDATE model_column
                        SET is_missing_in_source = 1,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE model_table_id = :table_id
                          AND origin = :origin
                          AND is_missing_in_source = 0
                          AND column_name NOT IN ({placeholders})
                        """,
                        params,
                    )
                    or 0
                )
        return total


def _to_table_record(row: Mapping[str, Any]) -> MetadataTableRecord:
    return MetadataTableRecord(
        table_id=int(row.get("id") or 0),
        table_name=str(row.get("name") or "").strip(),
        source_table_name=_clean_or_none(row.get("source_table_name")),
        description=_clean_or_none(row.get("description")),
        origin=_clean_or_none(row.get("origin")),
        is_missing_in_source=bool(row.get("is_missing_in_source")),
    )


def _to_column_record(row: Mapping[str, Any]) -> MetadataColumnRecord:
    confidence_raw = row.get("semantic_confidence")
    confidence = float(confidence_raw) if confidence_raw is not None else None
    return MetadataColumnRecord(
        column_id=int(row.get("id") or 0),
        table_id=int(row.get("model_table_id") or 0),
        column_name=str(row.get("column_name") or "").strip(),
        data_type=_clean_or_none(row.get("data_type")),
        description=_clean_or_none(row.get("description")),
        is_active=bool(row.get("is_active", True)),
        origin=_clean_or_none(row.get("origin")),
        is_missing_in_source=bool(row.get("is_missing_in_source")),
        semantic_type=_clean_or_none(row.get("semantic_type")),
        semantic_entity=_clean_or_none(row.get("semantic_entity")),
        semantic_sub_type=_clean_or_none(row.get("semantic_sub_type")),
        semantic_source=_clean_or_none(row.get("semantic_source")),
        semantic_confidence=confidence,
        semantic_concept_key=_clean_or_none(row.get("semantic_concept_key")),
    )


def _clean_or_none(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


__all__ = ["LegacyMetadataRepository"]
