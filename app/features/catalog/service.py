from __future__ import annotations

from dataclasses import dataclass

from flask import request

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.exceptions.forge_error import ForgeError
from app.ports.sql_executor import ForgeQueryPort
from app.routes.request_helpers import require_user_id
from app.services.value_overrides.list_read_service import ForgeListReadService
from app.services.value_overrides.list_writer import ForgeListWriter
from app.services.value_overrides.value_override_meta_writer import ValueOverrideMetaWriter
from app.services.workspace_inventory.workspace_context import WorkspaceSqlContextBuilder


@dataclass(frozen=True)
class ValueOverrideContext:
    workspace_id: str
    workspace_url: str
    warehouse_id: str
    user_name: str
    user_id: str
    sql_exec: ForgeQueryPort
    list_writer: ForgeListWriter
    qf_list_reader: ForgeListReadService
    meta_writer: ValueOverrideMetaWriter


class CatalogFeatureService:
    def extract_workspace_id(self) -> str:
        workspace_id = (request.headers.get("X-Workspace-Id") or "").strip()
        if not workspace_id:
            raise ForgeError("Missing X-Workspace-Id header", status_code=400)
        return workspace_id

    def build_value_override_context(self) -> ValueOverrideContext:
        workspace_id = self.extract_workspace_id()
        user_id = require_user_id()

        catalog_ctx = WorkspaceSqlContextBuilder().build(workspace_id)
        mysql_exec = ForgeMetaSQL()
        return ValueOverrideContext(
            workspace_id=workspace_id,
            workspace_url=catalog_ctx.workspace_url,
            warehouse_id=catalog_ctx.warehouse_id,
            user_name=catalog_ctx.user_name,
            user_id=user_id,
            sql_exec=catalog_ctx.sql_exec,
            list_writer=ForgeListWriter(sql=catalog_ctx.sql_exec),
            qf_list_reader=ForgeListReadService(
                mysql=mysql_exec,
                dbx=catalog_ctx.sql_exec,
                workspace_id=workspace_id,
                user_id=user_id,
            ),
            meta_writer=ValueOverrideMetaWriter(mysql_exec),
        )

    def int_arg(self, raw_value: str | None, *, default: int) -> int:
        raw = (raw_value or "").strip()
        return int(raw) if raw else default


catalog_feature_service = CatalogFeatureService()
