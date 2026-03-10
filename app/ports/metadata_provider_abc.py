# app/ports/metadata_provider_abc.py
from __future__ import annotations

from abc import ABC, abstractmethod


class MetadataProvider(ABC):
    """Abstract interface for analytics metadata discovery and column profiling.

    Concrete implementations wrap a ``SQLExecutor`` and query the source
    information schema.  This interface is intentionally separate from
    ``SQLExecutor`` — one concern is SQL execution, the other is metadata shape.
    """

    @abstractmethod
    def list_tables(self, catalog: str | None, schema: str) -> list[dict]:
        """Return table-level metadata for all tables in *schema*.

        :param catalog: Optional catalog/database qualifier.
        :param schema: Schema (or database) to inspect.
        :returns: List of dicts with at minimum:
            ``table_name``, ``table_type`` (TABLE/VIEW), ``comment``.
        """

    @abstractmethod
    def list_columns(
        self,
        catalog: str | None,
        schema: str,
        table_names: list[str] | None = None,
    ) -> list[dict]:
        """Return column-level metadata for tables in *schema*.

        :param catalog: Optional catalog qualifier.
        :param schema: Schema to inspect.
        :param table_names: Optional filter — if None, return all tables.
        :returns: List of dicts with at minimum:
            ``table_name``, ``column_name``, ``data_type``,
            ``ordinal_position``, ``is_nullable`` (bool), ``comment``.
        """

    @abstractmethod
    def profile_table_columns(
        self,
        table_ref: str,
        columns: list[dict],
        options: dict,
    ) -> dict:
        """Sample *table_ref* and compute per-column statistics.

        :param table_ref: Fully-qualified table reference, e.g. ``catalog.schema.table``.
        :param columns: Column dicts as returned by ``list_columns``.
        :param options: Profiling configuration (see ``ProfilingService`` for keys).
        :returns: Dict mapping ``column_name`` → stats dict with keys:
            ``null_count``, ``null_pct``, ``approx_distinct``,
            ``top_values`` (list of sampled unique values), ``sample_row_count``,
            ``sample_error`` (str|None).
        """

    @abstractmethod
    def list_schemas(self, catalog: str | None) -> list[str]:
        """Return sorted list of schema names visible to this datasource.

        :param catalog: Optional catalog context (e.g. Databricks Unity Catalog name).
            Pass ``None`` to query the executor's default catalog.
        :returns: Sorted list of schema name strings.
        :raises ValueError: if *catalog* contains unsafe characters.
        """
