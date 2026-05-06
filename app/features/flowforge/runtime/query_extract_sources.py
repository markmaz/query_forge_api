from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.exceptions.forge_error import ForgeError
from app.ports.sql_executor import ForgeQueryPort
from app.services.domain_resolver import DomainResolver
from app.services.query_forge.service import QueryForgeService
from app.services.workspace_inventory.workspace_context import WorkspaceSqlContextBuilder


@dataclass(frozen=True)
class QueryExtractSource:
    source_kind: str
    source_id: str
    display_name: str | None
    descriptor: dict[str, Any]


@dataclass(frozen=True)
class QueryExtractResult:
    rows: list[dict[str, Any]]
    columns: list[dict[str, Any]]
    total: int | None
    source: QueryExtractSource


class QueryExtractResolver(Protocol):
    def execute_preview(
        self,
        *,
        workspace_id: str,
        node_config: dict[str, Any],
        preview_limit: int,
    ) -> QueryExtractResult:
        ...


class QueryForgeSavedQueryExtractResolver:
    def __init__(
        self,
        *,
        sql: ForgeQueryPort | None = None,
        context_builder: WorkspaceSqlContextBuilder | None = None,
    ) -> None:
        self._sql = sql or ForgeMetaSQL()
        self._context_builder = context_builder or WorkspaceSqlContextBuilder()

    def execute_preview(
        self,
        *,
        workspace_id: str,
        node_config: dict[str, Any],
        preview_limit: int,
    ) -> QueryExtractResult:
        saved_query_id = str(node_config.get("saved_query_id") or "").strip()
        if saved_query_id:
            return self._execute_saved_query(
                workspace_id=workspace_id,
                saved_query_id=saved_query_id,
                preview_limit=preview_limit,
            )
        if node_config.get("semantic_plan_id"):
            raise ForgeError("semantic_plan_id query extracts require a semantic plan resolver.", status_code=400)
        if node_config.get("query_builder_artifact_id"):
            raise ForgeError("query_builder_artifact_id query extracts require an artifact resolver.", status_code=400)
        raise ForgeError("query_extract requires saved_query_id, semantic_plan_id, or query_builder_artifact_id.", status_code=400)

    def _execute_saved_query(self, *, workspace_id: str, saved_query_id: str, preview_limit: int) -> QueryExtractResult:
        rows = self._sql.execute_query_mappings(
            """
            SELECT sql_json, title
            FROM saved_query
            WHERE id = :saved_query_id
              AND (workspace_id = :workspace_id OR workspace_id IS NULL)
              AND is_deleted = 0
            LIMIT 1
            """,
            {"saved_query_id": saved_query_id, "workspace_id": workspace_id},
        )
        if not rows:
            raise ForgeError(f"Saved query '{saved_query_id}' was not found.", status_code=404)
        sql_json = self._decode_sql_json(rows[0].get("sql_json"))
        ctx = self._context_builder.build(workspace_id)
        result = QueryForgeService(
            executor=ctx.sql_exec,
            domain_resolver=DomainResolver(workspace_id=workspace_id),
        ).run(sql_json, mode="preview", limit=preview_limit, offset=0)
        return QueryExtractResult(
            rows=[dict(row) for row in result.rows],
            columns=[dict(column) for column in result.columns],
            total=int(result.total) if result.total is not None else len(result.rows),
            source=QueryExtractSource(
                source_kind="saved_query",
                source_id=saved_query_id,
                display_name=rows[0].get("title"),
                descriptor={"saved_query_id": saved_query_id},
            ),
        )

    @staticmethod
    def _decode_sql_json(value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return value
        if isinstance(value, str) and value.strip():
            return json.loads(value)
        return {}
