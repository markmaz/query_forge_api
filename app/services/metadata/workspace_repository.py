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
              wt.qf_table_name AS table_name,
              MAX(wt.source_table_name) AS source_table_name,
              MAX(wt.description) AS description,
              MAX(wt.origin) AS origin,
              MAX(CASE WHEN wt.is_missing_in_source = 1 THEN 1 ELSE 0 END) AS is_missing_in_source
            FROM workspace_table wt
            WHERE wt.qf_table_name = :table_name
            GROUP BY wt.qf_table_name
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
              wt.qf_table_name AS table_name,
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
              wt.qf_table_name AS table_name,
              MAX(wt.source_table_name) AS source_table_name,
              MAX(wt.description) AS description,
              MAX(wt.origin) AS origin,
              MAX(CASE WHEN wt.is_missing_in_source = 1 THEN 1 ELSE 0 END) AS is_missing_in_source
            FROM workspace_table wt
            WHERE (:q IS NULL OR wt.qf_table_name LIKE CONCAT('%', :q, '%'))
            GROUP BY wt.qf_table_name
            ORDER BY wt.qf_table_name
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
                    "model_table_id": int((table_id_by_name or {}).get(table_name) or 0) or None,
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
                        WHERE (
                            :model_table_id IS NOT NULL AND wt.model_table_id = :model_table_id
                        ) OR (
                            :model_table_id IS NULL AND wt.qf_table_name = :table_name
                        )
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
                          AND qf_table_name NOT IN ({placeholders})
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
            return {"columns_upserted": 0, "cols_by_table_id": {}}

        payload: List[Dict[str, Any]] = []
        cols_by_table_id: Dict[int, set[str]] = {}

        for col in columns:
            table_name = str(col.get("table_name") or "").strip()
            model_table_id = int(table_id_by_name.get(table_name) or 0)
            column_name = str(col.get("column_name") or "").strip()
            if not column_name:
                continue

            if model_table_id > 0:
                cols_by_table_id.setdefault(model_table_id, set()).add(column_name)

            payload.append(
                {
                    "table_name": table_name,
                    "model_table_id": model_table_id or None,
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
            return {"columns_upserted": 0, "cols_by_table_id": {}}

        total_affected = 0
        with self._sql.transaction() as tx:
            for batch in _chunk(payload, 2000):
                total_affected += int(
                    tx.execute_write(
                        """
                        UPDATE workspace_column wc
                        JOIN workspace_table wt ON wt.id = wc.workspace_table_id
                        SET wc.data_type = COALESCE(:data_type, wc.data_type),
                            wc.qf_ordinal_position = CASE
                                WHEN :ordinal_position > 0 THEN :ordinal_position
                                ELSE wc.qf_ordinal_position
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
                        WHERE (
                            :model_table_id IS NOT NULL AND wt.model_table_id = :model_table_id
                        ) OR (
                            :model_table_id IS NULL AND wt.qf_table_name = :table_name
                        )
                          AND wc.column_name = :column_name
                        """,
                        list(batch),
                    )
                    or 0
                )

        return {
            "columns_upserted": len(payload),
            "cols_by_table_id": {key: sorted(value) for key, value in cols_by_table_id.items()},
            "workspace_columns_updated": total_affected,
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
                        UPDATE workspace_column wc
                        JOIN workspace_table wt ON wt.id = wc.workspace_table_id
                        SET wc.is_missing_in_source = 1,
                            wc.metadata_updated_at = CURRENT_TIMESTAMP,
                            wc.updated_at = CURRENT_TIMESTAMP
                        WHERE wt.model_table_id = :table_id
                          AND wc.origin = :origin
                          AND wc.is_missing_in_source = 0
                          AND wc.column_name NOT IN ({placeholders})
                        """,
                        params,
                    )
                    or 0
                )
        return total

    def patch_table_by_model_table_id(self, *, model_table_id: int, updates: Mapping[str, Any]) -> int:
        if int(model_table_id) <= 0 or not updates:
            return 0
        allowed = {
            "qf_table_name",
            "source_table_name",
            "description",
            "origin",
            "is_missing_in_source",
            "sample_rows_json",
            "sample_ran_at",
            "sample_error",
        }
        sets: List[str] = []
        params: Dict[str, Any] = {"model_table_id": int(model_table_id)}
        for key, value in updates.items():
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
                WHERE model_table_id = :model_table_id
                """,
                params,
            )
            or 0
        )

    def patch_column_by_model_column_id(self, *, model_column_id: int, updates: Mapping[str, Any]) -> int:
        if int(model_column_id) <= 0 or not updates:
            return 0
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
            "qf_ordinal_position",
        }
        sets: List[str] = []
        params: Dict[str, Any] = {"model_column_id": int(model_column_id)}
        for key, value in updates.items():
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
                WHERE model_column_id = :model_column_id
                """,
                params,
            )
            or 0
        )

    def patch_column_by_model_table_and_name(
        self,
        *,
        model_table_id: int,
        column_name: str,
        updates: Mapping[str, Any],
    ) -> int:
        if int(model_table_id) <= 0 or not str(column_name or "").strip() or not updates:
            return 0
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
            "qf_ordinal_position",
        }
        sets: List[str] = []
        params: Dict[str, Any] = {
            "model_table_id": int(model_table_id),
            "column_name": str(column_name).strip(),
        }
        for key, value in updates.items():
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
                WHERE wt.model_table_id = :model_table_id
                  AND wc.column_name = :column_name
                """,
                params,
            )
            or 0
        )

    def deactivate_columns_not_in(self, *, model_table_id: int, keep_column_names: Iterable[str]) -> int:
        names = sorted({str(c or "").strip() for c in keep_column_names if str(c or "").strip()})
        if int(model_table_id) <= 0 or not names:
            return 0
        placeholders = ",".join(f":c{i}" for i in range(len(names)))
        params = {"model_table_id": int(model_table_id), **{f"c{i}": name for i, name in enumerate(names)}}
        return int(
            self._sql.execute_write(
                f"""
                UPDATE workspace_column wc
                JOIN workspace_table wt ON wt.id = wc.workspace_table_id
                SET wc.is_active = 0,
                    wc.metadata_updated_at = CURRENT_TIMESTAMP,
                    wc.updated_at = CURRENT_TIMESTAMP
                WHERE wt.model_table_id = :model_table_id
                  AND wc.is_active = 1
                  AND wc.column_name NOT IN ({placeholders})
                """,
                params,
            )
            or 0
        )

    def clear_model_column_reference(self, *, model_column_id: int) -> int:
        if int(model_column_id) <= 0:
            return 0
        return int(
            self._sql.execute_write(
                """
                UPDATE workspace_column
                SET model_column_id = NULL,
                    is_active = 0,
                    metadata_updated_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                WHERE model_column_id = :model_column_id
                """,
                {"model_column_id": int(model_column_id)},
            )
            or 0
        )

    def clear_model_table_reference(self, *, model_table_id: int) -> int:
        if int(model_table_id) <= 0:
            return 0
        return int(
            self._sql.execute_write(
                """
                UPDATE workspace_table
                SET model_table_id = NULL,
                    is_missing_in_source = 1,
                    metadata_updated_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                WHERE model_table_id = :model_table_id
                """,
                {"model_table_id": int(model_table_id)},
            )
            or 0
        )


__all__ = ["WorkspaceMetadataRepository"]
