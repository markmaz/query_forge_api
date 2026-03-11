# app/services/analytics/model_catalog_writer.py
from __future__ import annotations

from typing import Any

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.services.metadata.gateway import MetadataGateway


class ModelCatalogWriter:
    """Writer facade for metadata sync table/column upserts."""

    def __init__(self, *, mysql: ForgeMetaSQL | None = None, metadata_gateway: MetadataGateway | None = None) -> None:
        sql = mysql or ForgeMetaSQL()
        self._gateway = metadata_gateway or MetadataGateway(sql=sql)

    # ------------------------------------------------------------------
    # model_table
    # ------------------------------------------------------------------

    def upsert_tables(
        self,
        tables: list[dict],
        origin: str,
        overwrite_descriptions: bool = False,
    ) -> dict[str, Any]:
        return self._gateway.upsert_tables(
            tables=tables,
            origin=origin,
            overwrite_descriptions=overwrite_descriptions,
        )

    def mark_tables_missing(self, seen_names: set[str], origin: str) -> int:
        return self._gateway.mark_tables_missing(seen_names=seen_names, origin=origin)

    # ------------------------------------------------------------------
    # model_column
    # ------------------------------------------------------------------

    def upsert_columns(
        self,
        table_id_by_name: dict[str, int],
        columns: list[dict],
        origin: str,
        overwrite_descriptions: bool = False,
    ) -> dict[str, Any]:
        return self._gateway.upsert_columns(
            table_id_by_name=table_id_by_name,
            columns=columns,
            origin=origin,
            overwrite_descriptions=overwrite_descriptions,
        )

    def mark_columns_missing(
        self,
        cols_by_table_id: dict[int, set],
        origin: str,
        cols_by_table_name: dict[str, set] | None = None,
    ) -> int:
        return self._gateway.mark_columns_missing_v2(
            cols_by_table_id=cols_by_table_id,
            cols_by_table_name=cols_by_table_name or {},
            origin=origin,
        )
