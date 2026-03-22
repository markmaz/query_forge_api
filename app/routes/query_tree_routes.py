from __future__ import annotations

import logging
from typing import Any, Callable, Dict, Tuple

from flask import g, request
from flask_restx import Namespace, fields
from app.routes.forge_resource import ForgeResource

from app.decorators.security import token_required
from app.decorators.rbac import require_access
from app.exceptions.forge_error import ForgeError
from app.routes.request_helpers import require_user_id, extract_workspace_id
from app.services.query_tree.saved_query_folder_write_service import SavedQueryFolderWriteService
from app.services.query_tree.saved_query_library_service import SavedQueryLibraryService
from app.services.query_tree.saved_query_read_service import SavedQueryReadService
from app.services.query_tree.saved_query_share_service import SavedQueryShareService
from app.services.query_tree.saved_query_tree_service import SavedQueryTreeService
from app.services.query_tree.saved_query_write_service import SavedQueryWriteService

logger = logging.getLogger(__name__)

qf_tree_ns = Namespace("query-tree", description="Saved query tree (views + folders)")
qf_saved_query_ns = Namespace("saved-queries", description="Saved queries (read/move/trash)")

share_request_model = qf_saved_query_ns.model(
    "SavedQueryShareRequest",
    {
        "shareKind": fields.String(required=True, description="WORKSPACE|USER"),
        "sharedWithUserId": fields.String(required=False),
        "canEdit": fields.Boolean(required=False, default=False),
    },
)

share_response_model = qf_saved_query_ns.model(
    "SavedQueryShareResponse",
    {
        "aclId": fields.String,
        "queryId": fields.String,
        "principalType": fields.String,
        "principalId": fields.String,
        "permission": fields.String,
        "canEdit": fields.Boolean,
    },
)

share_list_item_model = qf_saved_query_ns.model(
    "SavedQueryShareListItem",
    {
        "aclId": fields.String,
        "principalType": fields.String,
        "principalId": fields.String,
        "permission": fields.String,
        "canEdit": fields.Boolean,
        "createdAt": fields.String,
    },
)

share_list_response_model = qf_saved_query_ns.model(
    "SavedQueryShareListResponse",
    {
        "queryId": fields.String,
        "shares": fields.List(fields.Nested(share_list_item_model)),
    },
)

unshare_response_model = qf_saved_query_ns.model(
    "SavedQueryUnshareResponse",
    {
        "queryId": fields.String,
        "shareKind": fields.String,
        "removed": fields.Boolean,
    },
)


def _handle_service_error(error: ForgeError) -> Tuple[Dict[str, Any], int]:
    return {"error": str(error)}, getattr(error, "status_code", 400) or 400


def _current_user_id() -> str:
    user_id = getattr(g, "user_id", None) or require_user_id()
    if not user_id:
        raise ForgeError("Missing user context", status_code=401)
    return str(user_id)


def _workspace_id() -> str:
    return extract_workspace_id()


def _user_display_name() -> str:
    return (getattr(g, "user_display_name", None) or getattr(g, "user_id", None) or "").strip()


def _json_body() -> Dict[str, Any]:
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        raise ForgeError("Invalid JSON body", status_code=400)
    return payload


def _effective_roles() -> set[str]:
    roles = getattr(g, "effective_roles", None)
    if roles is None:
        from app.services.rbac_service import get_effective_roles

        roles = get_effective_roles(_current_user_id(), workspace_id=getattr(g, "workspace_id", None))
        g.effective_roles = roles
    return set(roles)


def _can_publish_to_library() -> bool:
    roles = _effective_roles()
    return bool({"workspace_admin", "library_admin", "super_admin"} & roles)


def _can_delete_library_queries() -> bool:
    roles = _effective_roles()
    return bool({"workspace_admin", "library_admin", "super_admin"} & roles)


def _can_manage_library_items() -> bool:
    roles = _effective_roles()
    return bool({"workspace_admin", "library_admin", "super_admin"} & roles)


def _library_service() -> SavedQueryLibraryService:
    return SavedQueryLibraryService(
        workspace_id=_workspace_id(),
        user_id=_current_user_id(),
        allow_publish=_can_publish_to_library(),
        allow_delete_query=_can_delete_library_queries(),
        allow_manage=_can_manage_library_items(),
    )


def _run_route(error_message: str, fn: Callable[[], Tuple[Dict[str, Any], int]]) -> Tuple[Dict[str, Any], int]:
    try:
        return fn()
    except ForgeError as error:
        return _handle_service_error(error)
    except Exception:
        logger.exception(error_message)
        return {"error": error_message}, 500


@qf_tree_ns.route("/")
class QueryTree(ForgeResource):
    @token_required
    @require_access("query_studio")
    def get(self):
        def _execute():
            svc = SavedQueryTreeService(
                workspace_id=_workspace_id(),
                user_id=_current_user_id(),
                user_display_name=_user_display_name(),
            )
            view = (request.args.get("view") or "my").strip().lower()
            return svc.get_tree(view=view), 200

        return _run_route("Query tree fetch failed", _execute)


@qf_tree_ns.route("/folders")
class Folders(ForgeResource):
    @token_required
    @require_access("query_studio")
    def post(self):
        def _execute():
            payload = _json_body()
            if str(payload.get("scope") or "").strip().lower() == "library":
                svc = SavedQueryLibraryService(
                    workspace_id=_workspace_id(),
                    user_id=_current_user_id(),
                    allow_manage=_can_manage_library_items(),
                )
                return (
                    svc.create_folder(
                        name=payload.get("name"),
                        parent_folder_id=payload.get("parentId"),
                        sort_index=payload.get("sortIndex", 0),
                    ),
                    200,
                )

            svc = SavedQueryFolderWriteService(workspace_id=_workspace_id(), user_id=_current_user_id())
            return (
                svc.create_folder(
                    name=payload.get("name"),
                    parent_folder_id=payload.get("parentId"),
                    sort_index=payload.get("sortIndex", 0),
                ),
                200,
            )

        return _run_route("Folder create failed", _execute)


@qf_tree_ns.route("/folders/<string:folder_id>/rename")
class FolderRename(ForgeResource):
    @token_required
    @require_access("query_studio")
    def patch(self, folder_id: str):
        def _execute():
            payload = _json_body()
            library_svc = _library_service()
            if library_svc.folder_exists(folder_id):
                return library_svc.rename_folder(folder_id=folder_id, name=payload.get("name")), 200
            svc = SavedQueryFolderWriteService(workspace_id=_workspace_id(), user_id=_current_user_id())
            return svc.rename_folder(folder_id=folder_id, name=payload.get("name")), 200

        return _run_route("Folder rename failed", _execute)


@qf_tree_ns.route("/folders/<string:folder_id>/move")
class FolderMove(ForgeResource):
    @token_required
    @require_access("query_studio")
    def patch(self, folder_id: str):
        def _execute():
            payload = _json_body()
            library_svc = _library_service()
            if library_svc.folder_exists(folder_id):
                return (
                    library_svc.move_folder(
                        folder_id=folder_id,
                        parent_id=payload.get("parentId"),
                        sort_index=payload.get("sortIndex"),
                    ),
                    200,
                )
            svc = SavedQueryFolderWriteService(workspace_id=_workspace_id(), user_id=_current_user_id())
            return (
                svc.move_folder(
                    folder_id=folder_id,
                    new_parent_folder_id=payload.get("parentId"),
                    new_sort_index=payload.get("sortIndex"),
                ),
                200,
            )

        return _run_route("Folder move failed", _execute)


@qf_tree_ns.route("/folders/<string:folder_id>")
class FolderDelete(ForgeResource):
    @token_required
    @require_access("query_studio")
    def delete(self, folder_id: str):
        def _execute():
            library_svc = _library_service()
            if library_svc.folder_exists(folder_id):
                return library_svc.delete_folder(folder_id=folder_id), 200
            svc = SavedQueryFolderWriteService(workspace_id=_workspace_id(), user_id=_current_user_id())
            return svc.delete_folder(folder_id=folder_id), 200

        return _run_route("Folder delete failed", _execute)


@qf_tree_ns.route("/folders/<string:folder_id>/trash")
class FolderTrash(ForgeResource):
    @token_required
    @require_access("query_studio")
    def post(self, folder_id: str):
        def _execute():
            svc = SavedQueryFolderWriteService(workspace_id=_workspace_id(), user_id=_current_user_id())
            return svc.trash_folder(folder_id=folder_id), 200

        return _run_route("Folder trash failed", _execute)


@qf_tree_ns.route("/folders/<string:folder_id>/restore")
class FolderRestore(ForgeResource):
    @token_required
    @require_access("query_studio")
    def post(self, folder_id: str):
        def _execute():
            svc = SavedQueryFolderWriteService(workspace_id=_workspace_id(), user_id=_current_user_id())
            return svc.restore_folder(folder_id=folder_id), 200

        return _run_route("Folder restore failed", _execute)


@qf_tree_ns.route("/folders/<string:folder_id>/purge")
class FolderPurge(ForgeResource):
    @token_required
    @require_access("query_studio")
    def delete(self, folder_id: str):
        def _execute():
            svc = SavedQueryFolderWriteService(workspace_id=_workspace_id(), user_id=_current_user_id())
            return svc.purge_folder(folder_id=folder_id), 200

        return _run_route("Folder purge failed", _execute)


@qf_tree_ns.route("/recent")
class RecentQueries(ForgeResource):
    @token_required
    @require_access("query_studio")
    def get(self):
        def _execute():
            svc = SavedQueryReadService(
                workspace_id=_workspace_id(),
                user_id=_current_user_id(),
                is_admin=bool(getattr(g, "is_admin", False)),
            )
            return svc.fetch_recent_queries(limit=int(request.args.get("limit", 20))), 200

        return _run_route("Recent queries fetch failed", _execute)


@qf_saved_query_ns.route("/")
class SavedQueryCreate(ForgeResource):
    @token_required
    @require_access("query_studio")
    def post(self):
        def _execute():
            payload = _json_body()
            svc = SavedQueryWriteService(workspace_id=_workspace_id(), user_id=_current_user_id())
            return (
                svc.save_query(
                    title=payload.get("name") or payload.get("title"),
                    sql_json=payload.get("sqlJson") or payload.get("sql_json"),
                    description=payload.get("description"),
                    folder_id=payload.get("folderId"),
                    query_id=None,
                ),
                200,
            )

        return _run_route("Saved query create failed", _execute)


@qf_saved_query_ns.route("/<string:query_id>")
class SavedQuery(ForgeResource):
    @token_required
    @require_access("query_studio")
    def get(self, query_id: str):
        def _execute():
            svc = SavedQueryReadService(
                workspace_id=_workspace_id(),
                user_id=_current_user_id(),
                is_admin=bool(getattr(g, "is_admin", False)),
            )
            return svc.get_query(query_id), 200

        return _run_route("Saved query read failed", _execute)

    @token_required
    @require_access("query_studio")
    def patch(self, query_id: str):
        def _execute():
            payload = _json_body()
            library_svc = _library_service()
            if library_svc.query_exists(query_id):
                return (
                    library_svc.update_query(
                        query_id=query_id,
                        title=payload.get("name") or payload.get("title"),
                        sql_json=payload.get("sqlJson") or payload.get("sql_json"),
                        description=payload.get("description"),
                        folder_id=payload.get("folderId"),
                    ),
                    200,
                )
            svc = SavedQueryWriteService(workspace_id=_workspace_id(), user_id=_current_user_id())
            return (
                svc.save_query(
                    title=payload.get("name") or payload.get("title"),
                    sql_json=payload.get("sqlJson") or payload.get("sql_json"),
                    description=payload.get("description"),
                    folder_id=payload.get("folderId"),
                    query_id=query_id,
                ),
                200,
            )

        return _run_route("Saved query update failed", _execute)


@qf_saved_query_ns.route("/<string:query_id>/move")
class SavedQueryMove(ForgeResource):
    @token_required
    @require_access("query_studio")
    def patch(self, query_id: str):
        def _execute():
            payload = _json_body()
            library_svc = _library_service()
            if library_svc.query_exists(query_id):
                return library_svc.move_query(query_id=query_id, folder_id=payload.get("folderId")), 200
            svc = SavedQueryWriteService(workspace_id=_workspace_id(), user_id=_current_user_id())
            return svc.move_query(query_id=query_id, folder_id=payload.get("folderId")), 200

        return _run_route("Saved query move failed", _execute)


@qf_saved_query_ns.route("/<string:query_id>/delete")
class SavedQueryDelete(ForgeResource):
    @token_required
    @require_access("query_studio")
    def post(self, query_id: str):
        def _execute():
            library_svc = _library_service()
            if library_svc.query_exists(query_id):
                return library_svc.delete_query(query_id=query_id), 200
            svc = SavedQueryWriteService(workspace_id=_workspace_id(), user_id=_current_user_id())
            return svc.delete_query(query_id=query_id), 200

        return _run_route("Saved query delete failed", _execute)


@qf_saved_query_ns.route("/<string:query_id>/save-to-library")
class SavedQuerySaveToLibrary(ForgeResource):
    @token_required
    @require_access("query_studio")
    def post(self, query_id: str):
        def _execute():
            svc = _library_service()
            return svc.save_query_to_library(source_query_id=query_id), 200

        return _run_route("Saved query save to library failed", _execute)


@qf_saved_query_ns.route("/<string:query_id>/restore")
class SavedQueryRestore(ForgeResource):
    @token_required
    @require_access("query_studio")
    def post(self, query_id: str):
        def _execute():
            svc = SavedQueryWriteService(workspace_id=_workspace_id(), user_id=_current_user_id())
            return svc.restore_query(query_id=query_id), 200

        return _run_route("Saved query restore failed", _execute)


@qf_saved_query_ns.route("/<string:query_id>/purge")
class SavedQueryPurge(ForgeResource):
    @token_required
    @require_access("query_studio")
    def delete(self, query_id: str):
        def _execute():
            svc = SavedQueryWriteService(workspace_id=_workspace_id(), user_id=_current_user_id())
            return svc.purge_query(query_id=query_id), 200

        return _run_route("Saved query purge failed", _execute)


@qf_saved_query_ns.route("/<string:query_id>/shares")
class SavedQueryShares(ForgeResource):
    @token_required
    @require_access("query_studio")
    @qf_saved_query_ns.marshal_with(share_list_response_model, code=200)
    def get(self, query_id: str):
        def _execute():
            svc = SavedQueryShareService(workspace_id=_workspace_id(), user_id=_current_user_id())
            return svc.list_shares(query_id=query_id), 200

        return _run_route("Saved query shares fetch failed", _execute)

    @token_required
    @require_access("query_studio")
    @qf_saved_query_ns.expect(share_request_model)
    @qf_saved_query_ns.marshal_with(share_response_model, code=200)
    def post(self, query_id: str):
        def _execute():
            payload = _json_body()
            share_kind = (payload.get("shareKind") or "").strip().upper()
            can_edit = bool(payload.get("canEdit", False))
            if share_kind not in ("WORKSPACE", "USER"):
                raise ForgeError("Invalid shareKind", status_code=400)

            svc = SavedQueryShareService(workspace_id=_workspace_id(), user_id=_current_user_id())
            if share_kind == "WORKSPACE":
                return svc.share_to_workspace(query_id=query_id, can_edit=can_edit), 200

            shared_with = payload.get("sharedWithUserId")
            if not shared_with:
                raise ForgeError("sharedWithUserId is required", status_code=400)
            return (
                svc.share_to_user(query_id=query_id, shared_with_user_id=shared_with, can_edit=can_edit),
                200,
            )

        return _run_route("Saved query share failed", _execute)

    @token_required
    @require_access("query_studio")
    @qf_saved_query_ns.expect(share_request_model)
    @qf_saved_query_ns.marshal_with(unshare_response_model, code=200)
    def delete(self, query_id: str):
        def _execute():
            payload = _json_body()
            share_kind = (payload.get("shareKind") or "").strip().upper()
            if share_kind not in ("WORKSPACE", "USER"):
                raise ForgeError("Invalid shareKind", status_code=400)

            svc = SavedQueryShareService(workspace_id=_workspace_id(), user_id=_current_user_id())
            return (
                svc.unshare(
                    query_id=query_id,
                    share_kind=share_kind,
                    shared_with_user_id=payload.get("sharedWithUserId"),
                ),
                200,
            )

        return _run_route("Saved query unshare failed", _execute)
