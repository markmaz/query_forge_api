from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.ports.sql_executor import ForgeQueryPort
from app.services.metadata.types import MetadataColumnRecord, MetadataTableRecord


def _chunk(xs: Sequence[Any], n: int = 500) -> List[Sequence[Any]]:
    return [xs[i : i + n] for i in range(0, len(xs), n)]


def _clean_or_none(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


class WorkspaceMetadataRepository:
    """Metadata repository backed by workspace_table/workspace_column."""

    def __init__(self, *, sql: Optional[ForgeQueryPort] = None) -> None:
        self._sql = sql or ForgeMetaSQL()

    def get_table_by_name(self, *, table_name: str) -> Optional[MetadataTableRecord]:
        name = str(table_name or "").strip()
        if not name:
            return None
        rows = self._sql.execute_query_mappings(
            """
            SELECT
              MIN(wt.id) AS id,
              wt.table_name AS table_name,
              MAX(wt.source_table_name) AS source_table_name,
              MAX(wt.description) AS description,
              MAX(wt.origin) AS origin,
              MAX(CASE WHEN wt.is_missing_in_source = 1 THEN 1 ELSE 0 END) AS is_missing_in_source
            FROM workspace_table wt
            WHERE wt.table_name = :table_name
            GROUP BY wt.table_name
            LIMIT 1
            """,
            {"table_name": name},
        )
        if not rows:
            return None
        row = rows[0]
        return MetadataTableRecord(
            table_id=int(row.get("id") or 0),
            table_name=str(row.get("table_name") or "").strip(),
            source_table_name=_clean_or_none(row.get("source_table_name")),
            description=_clean_or_none(row.get("description")),
            origin=_clean_or_none(row.get("origin")),
            is_missing_in_source=bool(row.get("is_missing_in_source")),
        )

    def get_table_by_id(self, *, table_id: int) -> Optional[MetadataTableRecord]:
        rows = self._sql.execute_query_mappings(
            """
            SELECT
              wt.id,
              wt.table_name AS table_name,
              wt.source_table_name,
              wt.description,
              wt.origin,
              wt.is_missing_in_source
            FROM workspace_table wt
            WHERE wt.id = :id
            LIMIT 1
            """,
            {"id": int(table_id)},
        )
        if not rows:
            return None
        row = rows[0]
        return MetadataTableRecord(
            table_id=int(row.get("id") or 0),
            table_name=str(row.get("table_name") or "").strip(),
            source_table_name=_clean_or_none(row.get("source_table_name")),
            description=_clean_or_none(row.get("description")),
            origin=_clean_or_none(row.get("origin")),
            is_missing_in_source=bool(row.get("is_missing_in_source")),
        )

    def list_tables(
        self,
        *,
        q: Optional[str] = None,
        limit: int = 500,
        offset: int = 0,
    ) -> List[MetadataTableRecord]:
        rows = self._sql.execute_query_mappings(
            """
            SELECT
              MIN(wt.id) AS id,
              wt.table_name AS table_name,
              MAX(wt.source_table_name) AS source_table_name,
              MAX(wt.description) AS description,
              MAX(wt.origin) AS origin,
              MAX(CASE WHEN wt.is_missing_in_source = 1 THEN 1 ELSE 0 END) AS is_missing_in_source
            FROM workspace_table wt
            WHERE (:q IS NULL OR wt.table_name LIKE CONCAT('%', :q, '%'))
            GROUP BY wt.table_name
            ORDER BY wt.table_name
            LIMIT :limit OFFSET :offset
            """,
            {
                "q": str(q or "").strip() or None,
                "limit": int(limit),
                "offset": int(offset),
            },
        )
        out: List[MetadataTableRecord] = []
        for row in rows:
            out.append(
                MetadataTableRecord(
                    table_id=int(row.get("id") or 0),
                    table_name=str(row.get("table_name") or "").strip(),
                    source_table_name=_clean_or_none(row.get("source_table_name")),
                    description=_clean_or_none(row.get("description")),
                    origin=_clean_or_none(row.get("origin")),
                    is_missing_in_source=bool(row.get("is_missing_in_source")),
                )
            )
        return out

    def resolve_table_ids_by_names(self, *, names: Sequence[str]) -> Dict[str, int]:
        clean_names = sorted({str(name or "").strip() for name in names if str(name or "").strip()})
        if not clean_names:
            return {}
        out: Dict[str, int] = {}
        for batch in _chunk(clean_names, 500):
            placeholders = ", ".join(f":n{i}" for i in range(len(batch)))
            params = {f"n{i}": name for i, name in enumerate(batch)}
            rows = self._sql.execute_query_mappings(
                f"""
                SELECT MIN(id) AS id, table_name
                FROM workspace_table
                WHERE table_name IN ({placeholders})
                GROUP BY table_name
                """,
                params,
            )
            for row in rows:
                key = str(row.get("table_name") or row.get("name") or "")
                if key:
                    out[key] = int(row.get("id") or 0)
        return out

    def get_column_by_name(self, *, table_id: int, column_name: str) -> Optional[MetadataColumnRecord]:
        col = str(column_name or "").strip()
        if not col:
            return None
        rows = self._sql.execute_query_mappings(
            """
            SELECT
              wc.id,
              wc.workspace_table_id AS table_id,
              wc.column_name,
              wc.data_type,
              wc.description,
              wc.is_active,
              wc.origin,
              wc.is_missing_in_source,
              wc.semantic_type,
              wc.semantic_entity,
              wc.semantic_sub_type,
              wc.semantic_source,
              wc.semantic_confidence,
              wc.semantic_concept_key
            FROM workspace_column wc
            WHERE wc.workspace_table_id = :table_id
              AND wc.column_name = :column_name
            LIMIT 1
            """,
            {"table_id": int(table_id), "column_name": col},
        )
        if not rows:
            return None
        row = rows[0]
        confidence_raw = row.get("semantic_confidence")
        return MetadataColumnRecord(
            column_id=int(row.get("id") or 0),
            table_id=int(row.get("table_id") or 0),
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
            semantic_confidence=float(confidence_raw) if confidence_raw is not None else None,
            semantic_concept_key=_clean_or_none(row.get("semantic_concept_key")),
        )

    def upsert_tables(
        self,
        *,
        tables: Sequence[Mapping[str, Any]],
        origin: str,
        overwrite_descriptions: bool = False,
        table_id_by_name: Optional[Mapping[str, int]] = None,
    ) -> Dict[str, Any]:
        if not tables:
            return {"tables_upserted": 0}

        payload: List[Dict[str, Any]] = []
        for table in tables:
            table_name = str(table.get("table_name") or "").strip()
            if not table_name:
                continue
            payload.append(
                {
                    "table_name": table_name,
                    "source_table_name": str(table.get("source_table_name") or table_name).strip(),
                    "description": _clean_or_none(table.get("description") or table.get("comment")),
                    "origin": str(origin or "MANUAL").upper(),
                    "overwrite_descriptions": 1 if overwrite_descriptions else 0,
                }
            )
        if not payload:
            return {"tables_upserted": 0}

        total_affected = 0
        with self._sql.transaction() as tx:
            for batch in _chunk(payload, 500):
                total_affected += int(
                    tx.execute_write(
                        """
                        UPDATE workspace_table wt
                        SET wt.source_table_name = :source_table_name,
                            wt.description = CASE
                                WHEN :overwrite_descriptions = 1 THEN :description
                                ELSE COALESCE(wt.description, :description)
                            END,
                            wt.origin = :origin,
                            wt.is_missing_in_source = 0,
                            wt.metadata_synced_at = CURRENT_TIMESTAMP,
                            wt.metadata_updated_at = CURRENT_TIMESTAMP,
                            wt.updated_at = CURRENT_TIMESTAMP
                        WHERE wt.table_name = :table_name
                        """,
                        list(batch),
                    )
                    or 0
                )

        return {"tables_upserted": len(payload), "workspace_tables_updated": total_affected}

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
                        UPDATE workspace_table
                        SET is_missing_in_source = 1,
                            metadata_updated_at = CURRENT_TIMESTAMP,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE origin = :origin
                          AND is_missing_in_source = 0
                          AND table_name NOT IN ({placeholders})
                        """,
                        params,
                    )
                    or 0
                )
        return total

    def upsert_columns(
        self,
        *,
        table_id_by_name: Mapping[str, int],
        columns: Sequence[Mapping[str, Any]],
        origin: str,
        overwrite_descriptions: bool = False,
    ) -> Dict[str, Any]:
        if not columns:
            return {"columns_upserted": 0, "cols_by_table_id": {}, "cols_by_table_name": {}}

        payload: List[Dict[str, Any]] = []
        cols_by_table_name: Dict[str, set[str]] = {}

        for col in columns:
            table_name = str(col.get("table_name") or "").strip()
            column_name = str(col.get("column_name") or "").strip()
            if not column_name or not table_name:
                continue

            cols_by_table_name.setdefault(table_name, set()).add(column_name)

            payload.append(
                {
                    "table_name": table_name,
                    "column_name": column_name,
                    "data_type": _clean_or_none(col.get("data_type")),
                    "ordinal_position": int(col.get("ordinal_position") or 0),
                    "nullable": 1 if bool(col.get("is_nullable", True)) else 0,
                    "description": _clean_or_none(col.get("description") or col.get("comment")),
                    "origin": str(origin or "MANUAL").upper(),
                    "overwrite_descriptions": 1 if overwrite_descriptions else 0,
                }
            )

        if not payload:
            return {"columns_upserted": 0, "cols_by_table_id": {}, "cols_by_table_name": {}}

        total_affected = 0
        with self._sql.transaction() as tx:
            for batch in _chunk(payload, 2000):
                total_affected += int(
                    tx.execute_write(
                        """
                        UPDATE workspace_column wc
                        JOIN workspace_table wt ON wt.id = wc.workspace_table_id
                        SET wc.data_type = COALESCE(:data_type, wc.data_type),
                            wc.ordinal_position = CASE
                                WHEN :ordinal_position > 0 THEN :ordinal_position
                                ELSE wc.ordinal_position
                            END,
                            wc.nullable = :nullable,
                            wc.description = CASE
                                WHEN :overwrite_descriptions = 1 THEN :description
                                ELSE COALESCE(wc.description, :description)
                            END,
                            wc.is_active = 1,
                            wc.origin = :origin,
                            wc.is_missing_in_source = 0,
                            wc.metadata_updated_at = CURRENT_TIMESTAMP,
                            wc.updated_at = CURRENT_TIMESTAMP
                        WHERE wt.table_name = :table_name
                          AND wc.column_name = :column_name
                        """,
                        list(batch),
                    )
                    or 0
                )

        return {
            "columns_upserted": len(payload),
            "cols_by_table_id": {},
            "cols_by_table_name": {key: sorted(value) for key, value in cols_by_table_name.items()},
            "workspace_columns_updated": total_affected,
        }

    def mark_columns_missing(
        self,
        *,
        cols_by_table_id: Mapping[int, Iterable[str]] | None = None,
        cols_by_table_name: Mapping[str, Iterable[str]] | None = None,
        origin: str,
    ) -> int:
        total = 0
        with self._sql.transaction() as tx:
            name_map = dict(cols_by_table_name or {})
            if not name_map and cols_by_table_id:
                table_rows = self._sql.execute_query_mappings(
                    """
                    SELECT id, table_name
                    FROM workspace_table
                    WHERE id IN ({table_ids})
                    """.replace(
                        "{table_ids}",
                        ", ".join(f":t{i}" for i in range(len(cols_by_table_id))),
                    ),
                    {f"t{i}": int(table_id) for i, table_id in enumerate(cols_by_table_id.keys())},
                )
                id_to_name = {int(row["id"]): str(row.get("table_name") or "").strip() for row in table_rows}
                for table_id, columns in (cols_by_table_id or {}).items():
                    table_name = id_to_name.get(int(table_id))
                    if table_name:
                        name_map[table_name] = columns

            for table_name, columns in name_map.items():
                names = sorted({str(c or "").strip() for c in columns if str(c or "").strip()})
                if not names:
                    continue
                placeholders = ", ".join(f":c{i}" for i in range(len(names)))
                params = {
                    "table_name": str(table_name or "").strip(),
                    "origin": str(origin or "MANUAL").upper(),
                    **{f"c{i}": name for i, name in enumerate(names)},
                }
                total += int(
                    tx.execute_write(
                        f"""
                        UPDATE workspace_column wc
                        JOIN workspace_table wt ON wt.id = wc.workspace_table_id
                        SET wc.is_missing_in_source = 1,
                            wc.metadata_updated_at = CURRENT_TIMESTAMP,
                            wc.updated_at = CURRENT_TIMESTAMP
                        WHERE wt.table_name = :table_name
                          AND wc.origin = :origin
                          AND wc.is_missing_in_source = 0
                          AND wc.column_name NOT IN ({placeholders})
                        """,
                        params,
                    )
                    or 0
                )
        return total

    def patch_table_by_id(self, *, workspace_table_id: int, updates: Mapping[str, Any]) -> int:
        if int(workspace_table_id) <= 0 or not updates:
            return 0
        normalized_updates = dict(updates)
        if "qf_table_name" in normalized_updates and "table_name" not in normalized_updates:
            normalized_updates["table_name"] = normalized_updates["qf_table_name"]
        allowed = {
            "table_name",
            "source_table_name",
            "description",
            "origin",
            "is_missing_in_source",
            "sample_rows_json",
            "sample_ran_at",
            "sample_error",
        }
        sets: List[str] = []
        params: Dict[str, Any] = {"workspace_table_id": int(workspace_table_id)}
        for key, value in normalized_updates.items():
            if key not in allowed:
                continue
            sets.append(f"{key} = :{key}")
            params[key] = value
        if not sets:
            return 0
        sets.append("metadata_updated_at = CURRENT_TIMESTAMP")
        sets.append("updated_at = CURRENT_TIMESTAMP")
        return int(
            self._sql.execute_write(
                f"""
                UPDATE workspace_table
                SET {", ".join(sets)}
                WHERE id = :workspace_table_id
                """,
                params,
            )
            or 0
        )

    def patch_column_by_id(self, *, workspace_column_id: int, updates: Mapping[str, Any]) -> int:
        if int(workspace_column_id) <= 0 or not updates:
            return 0
        normalized_updates = dict(updates)
        if "qf_ordinal_position" in normalized_updates and "ordinal_position" not in normalized_updates:
            normalized_updates["ordinal_position"] = normalized_updates["qf_ordinal_position"]
        allowed = {
            "column_name",
            "data_type",
            "description",
            "is_active",
            "origin",
            "is_missing_in_source",
            "semantic_type",
            "semantic_entity",
            "semantic_sub_type",
            "semantic_source",
            "semantic_confidence",
            "semantic_concept_key",
            "semantic_concept_id",
            "semantic_assigned_at",
            "semantic_reasons_json",
            "sample_values_json",
            "sample_stats_json",
            "sample_ran_at",
            "sample_error",
            "nullable",
            "ordinal_position",
        }
        sets: List[str] = []
        params: Dict[str, Any] = {"workspace_column_id": int(workspace_column_id)}
        for key, value in normalized_updates.items():
            if key not in allowed:
                continue
            sets.append(f"{key} = :{key}")
            params[key] = value
        if not sets:
            return 0
        sets.append("metadata_updated_at = CURRENT_TIMESTAMP")
        sets.append("updated_at = CURRENT_TIMESTAMP")
        return int(
            self._sql.execute_write(
                f"""
                UPDATE workspace_column
                SET {", ".join(sets)}
                WHERE id = :workspace_column_id
                """,
                params,
            )
            or 0
        )

    def patch_column_by_table_and_name(
        self,
        *,
        workspace_table_id: int,
        column_name: str,
        updates: Mapping[str, Any],
    ) -> int:
        if int(workspace_table_id) <= 0 or not str(column_name or "").strip() or not updates:
            return 0
        normalized_updates = dict(updates)
        if "qf_ordinal_position" in normalized_updates and "ordinal_position" not in normalized_updates:
            normalized_updates["ordinal_position"] = normalized_updates["qf_ordinal_position"]
        allowed = {
            "data_type",
            "description",
            "is_active",
            "origin",
            "is_missing_in_source",
            "semantic_type",
            "semantic_entity",
            "semantic_sub_type",
            "semantic_source",
            "semantic_confidence",
            "semantic_concept_key",
            "semantic_concept_id",
            "semantic_assigned_at",
            "semantic_reasons_json",
            "sample_values_json",
            "sample_stats_json",
            "sample_ran_at",
            "sample_error",
            "nullable",
            "ordinal_position",
        }
        sets: List[str] = []
        params: Dict[str, Any] = {
            "workspace_table_id": int(workspace_table_id),
            "column_name": str(column_name).strip(),
        }
        for key, value in normalized_updates.items():
            if key not in allowed:
                continue
            sets.append(f"wc.{key} = :{key}")
            params[key] = value
        if not sets:
            return 0
        sets.append("wc.metadata_updated_at = CURRENT_TIMESTAMP")
        sets.append("wc.updated_at = CURRENT_TIMESTAMP")
        return int(
            self._sql.execute_write(
                f"""
                UPDATE workspace_column wc
                JOIN workspace_table wt ON wt.id = wc.workspace_table_id
                SET {", ".join(sets)}
                WHERE wt.id = :workspace_table_id
                  AND wc.column_name = :column_name
                """,
                params,
            )
            or 0
        )

    def deactivate_columns_not_in(
        self,
        *,
        workspace_table_id: int,
        keep_column_names: Iterable[str],
        origin: Optional[str] = None,
        only_not_missing: bool = False,
    ) -> int:
        names = sorted({str(c or "").strip() for c in keep_column_names if str(c or "").strip()})
        if int(workspace_table_id) <= 0 or not names:
            return 0
        placeholders = ",".join(f":c{i}" for i in range(len(names)))
        params = {
            "workspace_table_id": int(workspace_table_id),
            "origin": str(origin).upper() if origin is not None else None,
            **{f"c{i}": name for i, name in enumerate(names)},
        }
        extra_where = ""
        if origin is not None:
            extra_where += " AND wc.origin = :origin"
        if only_not_missing:
            extra_where += " AND wc.is_missing_in_source = 0"
        return int(
            self._sql.execute_write(
                f"""
                UPDATE workspace_column wc
                JOIN workspace_table wt ON wt.id = wc.workspace_table_id
                SET wc.is_active = 0,
                    wc.metadata_updated_at = CURRENT_TIMESTAMP,
                    wc.updated_at = CURRENT_TIMESTAMP
                WHERE wt.id = :workspace_table_id
                  AND wc.is_active = 1
                  {extra_where}
                  AND wc.column_name NOT IN ({placeholders})
                """,
                params,
            )
            or 0
        )

__all__ = ["WorkspaceMetadataRepository"]
