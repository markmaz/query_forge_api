from __future__ import annotations

from typing import Any, Dict, Iterable, Mapping, Optional, Sequence

from app.ports.sql_executor import ForgeQueryPort
from app.services.metadata.types import MetadataColumnRecord, MetadataTableRecord
from app.services.metadata.workspace_repository import WorkspaceMetadataRepository


class MetadataGateway:
    """Workspace-first facade for metadata operations."""

    def __init__(
        self,
        *,
        mode: Optional[str] = None,
        sql: Optional[ForgeQueryPort] = None,
        workspace_repo: Optional[WorkspaceMetadataRepository] = None,
        legacy_repo: Optional[object] = None,
    ) -> None:
        del mode, legacy_repo
        self._workspace = workspace_repo or WorkspaceMetadataRepository(sql=sql)

    @property
    def configured_mode(self) -> str:
        return "workspace"

    @property
    def effective_mode(self) -> str:
        return "workspace"

    def get_table_by_name(self, *, table_name: str) -> Optional[MetadataTableRecord]:
        return self._workspace.get_table_by_name(table_name=table_name)

    def get_table_by_id(self, *, table_id: int) -> Optional[MetadataTableRecord]:
        return self._workspace.get_table_by_id(table_id=table_id)

    def list_tables(self, *, q: Optional[str] = None, limit: int = 500, offset: int = 0) -> Sequence[MetadataTableRecord]:
        return self._workspace.list_tables(q=q, limit=limit, offset=offset)

    def upsert_tables(
        self,
        *,
        tables: Sequence[Mapping[str, Any]],
        origin: str,
        overwrite_descriptions: bool = False,
    ) -> Dict[str, Any]:
        result = self._workspace.upsert_tables(
            tables=tables,
            origin=origin,
            overwrite_descriptions=overwrite_descriptions,
        )
        names = [str(t.get("table_name") or "").strip() for t in tables if str(t.get("table_name") or "").strip()]
        result["name_to_id"] = self._workspace.resolve_table_ids_by_names(names=names)
        return result

    def mark_tables_missing(self, *, seen_names: Iterable[str], origin: str) -> int:
        return int(self._workspace.mark_tables_missing(seen_names=seen_names, origin=origin) or 0)

    def get_column_by_name(self, *, table_id: int, column_name: str) -> Optional[MetadataColumnRecord]:
        return self._workspace.get_column_by_name(table_id=table_id, column_name=column_name)

    def upsert_columns(
        self,
        *,
        table_id_by_name: Mapping[str, int],
        columns: Sequence[Mapping[str, Any]],
        origin: str,
        overwrite_descriptions: bool = False,
    ) -> Dict[str, Any]:
        return self._workspace.upsert_columns(
            table_id_by_name=table_id_by_name,
            columns=columns,
            origin=origin,
            overwrite_descriptions=overwrite_descriptions,
        )

    def mark_columns_missing(self, *, cols_by_table_id: Mapping[int, Iterable[str]], origin: str) -> int:
        return self.mark_columns_missing_v2(cols_by_table_id=cols_by_table_id, cols_by_table_name={}, origin=origin)

    def mark_columns_missing_v2(
        self,
        *,
        cols_by_table_id: Mapping[int, Iterable[str]],
        cols_by_table_name: Mapping[str, Iterable[str]],
        origin: str,
    ) -> int:
        return int(
            self._workspace.mark_columns_missing(
                cols_by_table_id=cols_by_table_id,
                cols_by_table_name=cols_by_table_name,
                origin=origin,
            )
            or 0
        )

    def sync_table_patch(self, *, workspace_table_id: int, updates: Mapping[str, Any]) -> int:
        return int(
            self._workspace.patch_table_by_id(
                workspace_table_id=workspace_table_id,
                updates=updates,
            )
            or 0
        )

    def sync_column_patch(self, *, workspace_column_id: int, updates: Mapping[str, Any]) -> int:
        return int(
            self._workspace.patch_column_by_id(
                workspace_column_id=workspace_column_id,
                updates=updates,
            )
            or 0
        )

    def sync_column_patch_by_table(
        self,
        *,
        workspace_table_id: int,
        column_name: str,
        updates: Mapping[str, Any],
    ) -> int:
        return int(
            self._workspace.patch_column_by_table_and_name(
                workspace_table_id=workspace_table_id,
                column_name=column_name,
                updates=updates,
            )
            or 0
        )

    def sync_column_profile(
        self,
        *,
        workspace_column_id: int,
        sample_values_json: str,
        sample_stats_json: str,
        sample_ran_at: Any,
        sample_error: Optional[str],
    ) -> int:
        return self.sync_column_patch(
            workspace_column_id=workspace_column_id,
            updates={
                "sample_values_json": sample_values_json,
                "sample_stats_json": sample_stats_json,
                "sample_ran_at": sample_ran_at,
                "sample_error": sample_error,
            },
        )

    def deactivate_workspace_columns_not_in(
        self,
        *,
        workspace_table_id: int,
        keep_column_names: Iterable[str],
        origin: Optional[str] = None,
        only_not_missing: bool = False,
    ) -> int:
        return int(
            self._workspace.deactivate_columns_not_in(
                workspace_table_id=workspace_table_id,
                keep_column_names=keep_column_names,
                origin=origin,
                only_not_missing=only_not_missing,
            )
            or 0
        )


__all__ = ["MetadataGateway"]
