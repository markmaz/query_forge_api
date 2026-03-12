from __future__ import annotations

import logging
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence

from app.config import METADATA_SOURCE_MODE
from app.exceptions.forge_error import ForgeError
from app.ports.sql_executor import ForgeQueryPort
from app.services.metadata.legacy_repository import LegacyMetadataRepository
from app.services.metadata.types import MetadataColumnRecord, MetadataTableRecord
from app.services.metadata.workspace_repository import WorkspaceMetadataRepository

_ALLOWED_MODES = {"legacy", "dual", "workspace"}
logger = logging.getLogger(__name__)


class MetadataGateway:
    """Facade for metadata operations with configurable legacy/dual/workspace writes."""

    def __init__(
        self,
        *,
        mode: Optional[str] = None,
        sql: Optional[ForgeQueryPort] = None,
        legacy_repo: Optional[LegacyMetadataRepository] = None,
        workspace_repo: Optional[WorkspaceMetadataRepository] = None,
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
        self._workspace = workspace_repo or WorkspaceMetadataRepository(sql=sql)

    @property
    def configured_mode(self) -> str:
        return self._mode

    @property
    def effective_mode(self) -> str:
        return self._mode

    def _legacy_enabled(self) -> bool:
        return self._mode in {"legacy", "dual"}

    def _workspace_enabled(self) -> bool:
        return self._mode in {"dual", "workspace"}

    def _safe_workspace_write(self, *, action: str, fn, **kwargs):
        if not self._workspace_enabled():
            return None
        try:
            return fn(**kwargs)
        except Exception as exc:
            if self._mode == "workspace":
                raise ForgeError(
                    f"workspace metadata write failed ({action})",
                    status_code=500,
                    details={"action": action},
                ) from exc
            logger.exception("MetadataGateway dual-write workspace failure action=%s", action)
            return None

    def get_table_by_name(self, *, table_name: str) -> Optional[MetadataTableRecord]:
        if self._mode == "workspace":
            return self._workspace.get_table_by_name(table_name=table_name)
        return self._legacy.get_table_by_name(table_name=table_name)

    def get_table_by_id(self, *, table_id: int) -> Optional[MetadataTableRecord]:
        if self._mode == "workspace":
            return self._workspace.get_table_by_id(table_id=table_id)
        return self._legacy.get_table_by_id(table_id=table_id)

    def list_tables(self, *, q: Optional[str] = None, limit: int = 500, offset: int = 0) -> Sequence[MetadataTableRecord]:
        if self._mode == "workspace":
            return self._workspace.list_tables(q=q, limit=limit, offset=offset)
        return self._legacy.list_tables(q=q, limit=limit, offset=offset)

    def upsert_tables(
        self,
        *,
        tables: Sequence[Mapping[str, Any]],
        origin: str,
        overwrite_descriptions: bool = False,
    ) -> Dict[str, Any]:
        names = [str(t.get("table_name") or "").strip() for t in tables if str(t.get("table_name") or "").strip()]

        legacy_result: Dict[str, Any]
        if self._legacy_enabled():
            legacy_result = self._legacy.upsert_tables(
                tables=tables,
                origin=origin,
                overwrite_descriptions=overwrite_descriptions,
            )
        else:
            legacy_result = {
                "tables_upserted": len(names),
                "name_to_id": self._workspace.resolve_table_ids_by_names(names=names),
            }

        self._safe_workspace_write(
            action="upsert_tables",
            fn=self._workspace.upsert_tables,
            tables=tables,
            origin=origin,
            overwrite_descriptions=overwrite_descriptions,
            table_id_by_name=legacy_result.get("name_to_id") or {},
        )
        return legacy_result

    def mark_tables_missing(self, *, seen_names: Iterable[str], origin: str) -> int:
        legacy_affected = 0
        if self._legacy_enabled():
            legacy_affected = self._legacy.mark_tables_missing(seen_names=seen_names, origin=origin)
        self._safe_workspace_write(
            action="mark_tables_missing",
            fn=self._workspace.mark_tables_missing,
            seen_names=seen_names,
            origin=origin,
        )
        return legacy_affected

    def get_column_by_name(self, *, table_id: int, column_name: str) -> Optional[MetadataColumnRecord]:
        if self._mode == "workspace":
            return self._workspace.get_column_by_name(table_id=table_id, column_name=column_name)
        return self._legacy.get_column_by_name(table_id=table_id, column_name=column_name)

    def upsert_columns(
        self,
        *,
        table_id_by_name: Mapping[str, int],
        columns: Sequence[Mapping[str, Any]],
        origin: str,
        overwrite_descriptions: bool = False,
    ) -> Dict[str, Any]:
        legacy_result: Dict[str, Any]
        if self._legacy_enabled():
            legacy_result = self._legacy.upsert_columns(
                table_id_by_name=table_id_by_name,
                columns=columns,
                origin=origin,
                overwrite_descriptions=overwrite_descriptions,
            )
        else:
            legacy_result = {
                "columns_upserted": len(columns),
                "cols_by_table_id": {},
            }

        self._safe_workspace_write(
            action="upsert_columns",
            fn=self._workspace.upsert_columns,
            table_id_by_name=table_id_by_name,
            columns=columns,
            origin=origin,
            overwrite_descriptions=overwrite_descriptions,
        )
        return legacy_result

    def mark_columns_missing(self, *, cols_by_table_id: Mapping[int, Iterable[str]], origin: str) -> int:
        return self.mark_columns_missing_v2(cols_by_table_id=cols_by_table_id, cols_by_table_name={}, origin=origin)

    def mark_columns_missing_v2(
        self,
        *,
        cols_by_table_id: Mapping[int, Iterable[str]],
        cols_by_table_name: Mapping[str, Iterable[str]],
        origin: str,
    ) -> int:
        legacy_affected = 0
        if self._legacy_enabled():
            legacy_affected = self._legacy.mark_columns_missing(cols_by_table_id=cols_by_table_id, origin=origin)
        self._safe_workspace_write(
            action="mark_columns_missing",
            fn=self._workspace.mark_columns_missing,
            cols_by_table_id=cols_by_table_id,
            cols_by_table_name=cols_by_table_name,
            origin=origin,
        )
        return legacy_affected

    # Explicit workspace mirror helpers used by model/semantic/profiling writers.

    def sync_table_patch_from_model(self, *, model_table_id: int, updates: Mapping[str, Any]) -> int:
        out = self._safe_workspace_write(
            action="sync_table_patch_from_model",
            fn=self._workspace.patch_table_by_model_table_id,
            model_table_id=model_table_id,
            updates=updates,
        )
        return int(out or 0)

    def sync_column_patch_from_model(self, *, model_column_id: int, updates: Mapping[str, Any]) -> int:
        out = self._safe_workspace_write(
            action="sync_column_patch_from_model",
            fn=self._workspace.patch_column_by_model_column_id,
            model_column_id=model_column_id,
            updates=updates,
        )
        return int(out or 0)

    def sync_column_patch_from_model_table(
        self,
        *,
        model_table_id: int,
        column_name: str,
        updates: Mapping[str, Any],
    ) -> int:
        out = self._safe_workspace_write(
            action="sync_column_patch_from_model_table",
            fn=self._workspace.patch_column_by_model_table_and_name,
            model_table_id=model_table_id,
            column_name=column_name,
            updates=updates,
        )
        return int(out or 0)

    def sync_column_profile_from_model_table(
        self,
        *,
        model_table_id: int,
        column_name: str,
        sample_values_json: str,
        sample_stats_json: str,
        sample_ran_at: Any,
        sample_error: Optional[str],
    ) -> int:
        updates: Dict[str, Any] = {
            "sample_values_json": sample_values_json,
            "sample_stats_json": sample_stats_json,
            "sample_ran_at": sample_ran_at,
            "sample_error": sample_error,
        }
        return self.sync_column_patch_from_model_table(
            model_table_id=model_table_id,
            column_name=column_name,
            updates=updates,
        )

    def sync_column_profile_from_model_column(
        self,
        *,
        model_column_id: int,
        sample_values_json: str,
        sample_stats_json: str,
        sample_ran_at: Any,
        sample_error: Optional[str],
    ) -> int:
        return self.sync_column_patch_from_model(
            model_column_id=model_column_id,
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
        model_table_id: int,
        keep_column_names: Iterable[str],
        origin: Optional[str] = None,
        only_not_missing: bool = False,
    ) -> int:
        out = self._safe_workspace_write(
            action="deactivate_workspace_columns_not_in",
            fn=self._workspace.deactivate_columns_not_in,
            model_table_id=model_table_id,
            keep_column_names=keep_column_names,
            origin=origin,
            only_not_missing=only_not_missing,
        )
        return int(out or 0)

    def clear_workspace_model_column_reference(self, *, model_column_id: int) -> int:
        out = self._safe_workspace_write(
            action="clear_workspace_model_column_reference",
            fn=self._workspace.clear_model_column_reference,
            model_column_id=model_column_id,
        )
        return int(out or 0)

    def clear_workspace_model_table_reference(self, *, model_table_id: int) -> int:
        out = self._safe_workspace_write(
            action="clear_workspace_model_table_reference",
            fn=self._workspace.clear_model_table_reference,
            model_table_id=model_table_id,
        )
        return int(out or 0)

    def mirror_primary_semantic_keys_from_model(self, *, workspace_id: Optional[str] = None) -> int:
        out = self._safe_workspace_write(
            action="mirror_primary_semantic_keys_from_model",
            fn=self._workspace.mirror_primary_semantic_keys_from_model,
            workspace_id=workspace_id,
        )
        return int(out or 0)


__all__ = ["MetadataGateway"]
