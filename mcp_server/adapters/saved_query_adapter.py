from __future__ import annotations

from app.services.domain_resolver import DomainResolver
from app.services.query_forge.service import QueryForgeService
from app.services.query_tree.saved_query_read_service import SavedQueryReadService
from app.services.workspace_inventory.workspace_context import WorkspaceSqlContextBuilder

from ..config import MCPSettings
from ..context import RequestContext
from ..exceptions import MCPError
from ..schemas.common import ColumnSchema
from ..schemas.saved_queries import ListSavedQueriesResponse, RunSavedQueryResponse, SavedQueryItem
from .domain_adapter import DomainAdapter


class SavedQueryAdapter:
    def __init__(
        self,
        *,
        settings: MCPSettings,
        context_builder: WorkspaceSqlContextBuilder | None = None,
        domain_adapter: DomainAdapter | None = None,
    ) -> None:
        self._settings = settings
        self._context_builder = context_builder or WorkspaceSqlContextBuilder()
        self._domains = domain_adapter or DomainAdapter()

    def list_saved_queries(
        self,
        *,
        request_context: RequestContext,
        folder_id: str | None,
    ) -> ListSavedQueriesResponse:
        if not request_context.can_run_saved_queries:
            raise MCPError(
                error_code="FORBIDDEN",
                message="Saved query access is not enabled for this caller",
                status_code=403,
            )
        service = SavedQueryReadService(
            workspace_id=request_context.workspace_id,
            user_id=request_context.user_id,
            is_admin=request_context.is_admin,
        )
        visible_domains = {
            int(row["id"]): str(row.get("key") or "")
            for row in self._domains.list_visible_domains(request_context=request_context)
            if row.get("id") is not None
        }
        items: list[SavedQueryItem] = []
        seen_ids: set[str] = set()
        for view in ("my", "shared", "library"):
            tree = service.get_tree(view=view)
            for node in self._flatten_query_nodes(list(tree.get("rootNodes") or [])):
                query_id = str(node.get("id") or "")
                if query_id == "" or query_id in seen_ids:
                    continue
                if folder_id and str(node.get("folderId") or "") != str(folder_id):
                    continue
                seen_ids.add(query_id)
                detail = service.get_query(query_id)
                sql_json = dict(detail.get("sqlJson") or {})
                domain_id = sql_json.get("domainId")
                items.append(
                    SavedQueryItem(
                        query_id=query_id,
                        name=str(detail.get("name") or node.get("name") or "Untitled"),
                        owner_scope=self._owner_scope_from_saved_query(detail),
                        domain_key=visible_domains.get(int(domain_id)) if domain_id is not None else None,
                        updated_at=detail.get("updatedAt"),
                    )
                )
        return ListSavedQueriesResponse(items=items)

    def run_saved_query(
        self,
        *,
        request_context: RequestContext,
        query_id: str,
        limit: int,
    ) -> RunSavedQueryResponse:
        if not request_context.can_run_saved_queries:
            raise MCPError(
                error_code="FORBIDDEN",
                message="Saved query execution is not enabled for this caller",
                status_code=403,
            )
        requested_limit = int(limit or self._settings.preview_default_limit)
        if requested_limit > self._settings.preview_hard_limit:
            raise MCPError(
                error_code="PREVIEW_LIMIT_EXCEEDED",
                message=f"Saved query preview limit exceeds hard max of {self._settings.preview_hard_limit}",
                status_code=400,
            )
        effective_limit = min(requested_limit, self._settings.preview_default_limit)
        service = SavedQueryReadService(
            workspace_id=request_context.workspace_id,
            user_id=request_context.user_id,
            is_admin=request_context.is_admin,
        )
        detail = service.get_query(query_id)
        sql_json = dict(detail.get("sqlJson") or {})
        ctx = self._context_builder.build(request_context.workspace_id)
        qf = QueryForgeService(
            executor=ctx.sql_exec,
            domain_resolver=DomainResolver(workspace_id=request_context.workspace_id),
        )
        result = qf.run(sql_json, mode="preview", limit=effective_limit, offset=0)
        return RunSavedQueryResponse(
            query_id=query_id,
            columns=[
                ColumnSchema(
                    name=str(col.get("name") or col.get("key") or ""),
                    type=str(col.get("type") or col.get("dataType") or col.get("data_type") or ""),
                    label=str(col.get("label") or col.get("name") or col.get("key") or ""),
                )
                for col in list(result.columns or [])
            ],
            rows=[dict(row) for row in list(result.rows or [])],
            truncated=bool((result.total or 0) > len(result.rows or [])),
        )

    def saved_queries_resource(self, *, request_context: RequestContext) -> dict[str, Any]:
        listing = self.list_saved_queries(request_context=request_context, folder_id=None)
        return {
            "workspace_id": request_context.workspace_id,
            "items": [item.model_dump(mode="json") for item in listing.items],
        }

    @staticmethod
    def _flatten_query_nodes(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for node in nodes:
            if str(node.get("nodeType") or "") == "query":
                rows.append(dict(node))
            rows.extend(SavedQueryAdapter._flatten_query_nodes(list(node.get("children") or [])))
        return rows

    @staticmethod
    def _owner_scope_from_saved_query(payload: dict[str, Any]) -> str:
        scope = str(payload.get("scope") or "").strip().upper()
        if scope == "LIBRARY":
            return "global"
        if scope == "MINE":
            return "user"
        return "workspace"
