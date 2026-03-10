from __future__ import annotations

from typing import Any, Dict, Iterable, Mapping, Optional, Sequence

from app.config import METADATA_SOURCE_MODE
from app.exceptions.forge_error import ForgeError
from app.ports.sql_executor import ForgeQueryPort
from app.services.metadata.legacy_repository import LegacyMetadataRepository
from app.services.metadata.types import MetadataColumnRecord, MetadataTableRecord

_ALLOWED_MODES = {"legacy", "dual", "workspace"}


class MetadataGateway:
    """Facade for metadata operations.

    PR-01 behavior:
    - Supports mode selection (legacy|dual|workspace)
    - All modes currently execute against legacy repository to avoid behavior changes.
    - Future PRs will implement true dual/workspace execution.
    """

    def __init__(
        self,
        *,
        mode: Optional[str] = None,
        sql: Optional[ForgeQueryPort] = None,
        legacy_repo: Optional[LegacyMetadataRepository] = None,
    ) -> None:
        resolved_mode = str(mode or METADATA_SOURCE_MODE or "legacy").strip().lower() or "legacy"
        if resolved_mode not in _ALLOWED_MODES:
            raise ForgeError(
                "Invalid METADATA_SOURCE_MODE",
                status_code=500,
                details={"mode": resolved_mode, "allowed": sorted(_ALLOWED_MODES)},
            )

        self._mode = resolved_mode
        self._legacy = legacy_repo or LegacyMetadataRepository(sql=sql)

    @property
    def configured_mode(self) -> str:
        return self._mode

    @property
    def effective_mode(self) -> str:
        # PR-01: dual/workspace still run legacy behavior.
        return "legacy"

    def get_table_by_name(self, *, table_name: str) -> Optional[MetadataTableRecord]:
        return self._legacy.get_table_by_name(table_name=table_name)

    def get_table_by_id(self, *, table_id: int) -> Optional[MetadataTableRecord]:
        return self._legacy.get_table_by_id(table_id=table_id)

    def list_tables(self, *, q: Optional[str] = None, limit: int = 500, offset: int = 0) -> Sequence[MetadataTableRecord]:
        return self._legacy.list_tables(q=q, limit=limit, offset=offset)

    def upsert_tables(
        self,
        *,
        tables: Sequence[Mapping[str, Any]],
        origin: str,
        overwrite_descriptions: bool = False,
    ) -> Dict[str, Any]:
        return self._legacy.upsert_tables(
            tables=tables,
            origin=origin,
            overwrite_descriptions=overwrite_descriptions,
        )

    def mark_tables_missing(self, *, seen_names: Iterable[str], origin: str) -> int:
        return self._legacy.mark_tables_missing(seen_names=seen_names, origin=origin)

    def get_column_by_name(self, *, table_id: int, column_name: str) -> Optional[MetadataColumnRecord]:
        return self._legacy.get_column_by_name(table_id=table_id, column_name=column_name)

    def upsert_columns(
        self,
        *,
        table_id_by_name: Mapping[str, int],
        columns: Sequence[Mapping[str, Any]],
        origin: str,
        overwrite_descriptions: bool = False,
    ) -> Dict[str, Any]:
        return self._legacy.upsert_columns(
            table_id_by_name=table_id_by_name,
            columns=columns,
            origin=origin,
            overwrite_descriptions=overwrite_descriptions,
        )

    def mark_columns_missing(self, *, cols_by_table_id: Mapping[int, Iterable[str]], origin: str) -> int:
        return self._legacy.mark_columns_missing(cols_by_table_id=cols_by_table_id, origin=origin)


__all__ = ["MetadataGateway"]
