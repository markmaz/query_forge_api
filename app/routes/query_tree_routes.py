from __future__ import annotations

import logging

from flask import g, request
from flask_restx import Namespace, Resource, fields

from app.decorators.security import token_required
from app.exceptions.service_error import ServiceError
from app.routes._route_utils import get_user_id, get_workspace_id_from_header
from app.services.query_tree.cohort_visibility_service import CohortVisibilityService
from app.services.query_tree.saved_query_folder_write_service import SavedQueryFolderWriteService
from app.services.query_tree.saved_query_read_service import SavedQueryReadService
from app.services.query_tree.saved_query_share_service import SavedQueryShareService
from app.services.query_tree.saved_query_tree_service import SavedQueryTreeService
from app.services.query_tree.saved_query_write_service import SavedQueryWriteService

logger = logging.getLogger(__name__)

tree_ns = Namespace("query-tree", description="Saved query tree (views + folders)")
saved_query_ns = Namespace("saved-queries", description="Saved queries (read/move/trash)")

share_request_model = saved_query_ns.model(
    "SavedQueryShareRequest",
    {
        "shareKind": fields.String(required=True, description="WORKSPACE|USER"),
        "sharedWithUserId": fields.String(required=False),
        "canEdit": fields.Boolean(required=False, default=False),
    },
)

share_response_model = saved_query_ns.model(
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

share_list_item_model = saved_query_ns.model(
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

share_list_response_model = saved_query_ns.model(
    "SavedQueryShareListResponse",
    {
        "queryId": fields.String,
        "shares": fields.List(fields.Nested(share_list_item_model)),
    },
)

unshare_response_model = saved_query_ns.model(
    "SavedQueryUnshareResponse",
    {
        "queryId": fields.String,
        "shareKind": fields.String,
        "removed": fields.Boolean,
    },
)


def _handle_service_error(e: ServiceError):
    return {"error": str(e)}, getattr(e, "status_code", 400) or 400


def _get_user_display_name() -> str:
    return (getattr(g, "user_display_name", None) or getattr(g, "user_id", None) or "").strip()


# -------------------------
# Query tree
# -------------------------
@tree_ns.route("/")
class QueryTree(Resource):
    @token_required
    def get(self):
        """
        GET /query-tree?view=my|shared|library|trash
        Headers: X-Workspace-Id
        """
        try:
            workspace_id = get_workspace_id_from_header()
            user_id = getattr(g, "user_id", None)
            display_name = _get_user_display_name()
            view = (request.args.get("view") or "my").strip().lower()

            if not user_id:
                raise ServiceError("Missing user context", status_code=401)

            svc = SavedQueryTreeService(workspace_id=workspace_id, user_id=user_id, user_display_name=display_name)
            return svc.get_tree(view=view), 200
        except ServiceError as e:
            return _handle_service_error(e)
        except Exception:
            logger.exception("Query tree fetch failed")
            return {"error": "Query tree fetch failed"}, 500


@tree_ns.route("/folders")
class Folders(Resource):
    @token_required
    def post(self):
        """
        POST /query-tree/folders
        Body: { "name": "...", "parentId": null|folderId, "sortIndex": 0 }
        """
        try:
            workspace_id = get_workspace_id_from_header()
            user_id = getattr(g, "user_id", None)
            payload = request.get_json(silent=True) or {}
            if not isinstance(payload, dict):
                raise ServiceError("Invalid JSON body", status_code=400)
            if not user_id:
                raise ServiceError("Missing user context", status_code=401)

            name = payload.get("name")
            parent_id = payload.get("parentId")
            sort_index = payload.get("sortIndex", 0)

            svc = SavedQueryFolderWriteService(workspace_id=workspace_id, user_id=user_id)
            res = svc.create_folder(name=name, parent_folder_id=parent_id, sort_index=sort_index)
            return res, 200
        except ServiceError as e:
            return _handle_service_error(e)
        except Exception:
            logger.exception("Folder create failed")
            return {"error": "Folder create failed"}, 500


@tree_ns.route("/folders/<string:folder_id>/rename")
class FolderRename(Resource):
    @token_required
    def patch(self, folder_id: str):
        """
        PATCH /query-tree/folders/<folder_id>/rename
        Body: { "name": "New name" }
        """
        try:
            workspace_id = get_workspace_id_from_header()
            user_id = getattr(g, "user_id", None)
            payload = request.get_json(silent=True) or {}
            name = (payload.get("name") if isinstance(payload, dict) else None)

            if not user_id:
                raise ServiceError("Missing user context", status_code=401)
            svc = SavedQueryFolderWriteService(workspace_id=workspace_id, user_id=user_id)
            return svc.rename_folder(folder_id=folder_id, name=name), 200
        except ServiceError as e:
            return _handle_service_error(e)
        except Exception:
            logger.exception("Folder rename failed")
            return {"error": "Folder rename failed"}, 500


@tree_ns.route("/folders/<string:folder_id>/move")
class FolderMove(Resource):
    @token_required
    def patch(self, folder_id: str):
        """
        PATCH /query-tree/folders/<folder_id>/move
        Body: { "parentId": null|folderId, "sortIndex": <int|null> }
        """
        try:
            workspace_id = get_workspace_id_from_header()
            user_id = getattr(g, "user_id", None)
            payload = request.get_json(silent=True) or {}
            if not isinstance(payload, dict):
                raise ServiceError("Invalid JSON body", status_code=400)

            parent_id = payload.get("parentId")
            sort_index = payload.get("sortIndex")

            if not user_id:
                raise ServiceError("Missing user context", status_code=401)
            svc = SavedQueryFolderWriteService(workspace_id=workspace_id, user_id=user_id)
            return svc.move_folder(folder_id=folder_id, new_parent_folder_id=parent_id, new_sort_index=sort_index), 200
        except ServiceError as e:
            return _handle_service_error(e)
        except Exception:
            logger.exception("Folder move failed")
            return {"error": "Folder move failed"}, 500


@tree_ns.route("/folders/<string:folder_id>")
class FolderDelete(Resource):
    @token_required
    def delete(self, folder_id: str):
        """
        DELETE /query-tree/folders/<folder_id>
        Soft-deletes only if empty. For recursive delete, use /trash.
        """
        try:
            workspace_id = get_workspace_id_from_header()
            user_id = getattr(g, "user_id", None)
            if not user_id:
                raise ServiceError("Missing user context", status_code=401)
            svc = SavedQueryFolderWriteService(workspace_id=workspace_id, user_id=user_id)
            return svc.delete_folder(folder_id=folder_id), 200
        except ServiceError as e:
            return _handle_service_error(e)
        except Exception:
            logger.exception("Folder delete failed")
            return {"error": "Folder delete failed"}, 500


@tree_ns.route("/folders/<string:folder_id>/trash")
class FolderTrash(Resource):
    @token_required
    def post(self, folder_id: str):
        """
        POST /query-tree/folders/<folder_id>/trash
        Soft-delete folder subtree (folders + queries).
        """
        try:
            workspace_id = get_workspace_id_from_header()
            user_id = getattr(g, "user_id", None)
            if not user_id:
                raise ServiceError("Missing user context", status_code=401)
            svc = SavedQueryFolderWriteService(workspace_id=workspace_id, user_id=user_id)
            return svc.trash_folder(folder_id=folder_id), 200
        except ServiceError as e:
            return _handle_service_error(e)
        except Exception:
            logger.exception("Folder trash failed")
            return {"error": "Folder trash failed"}, 500


@tree_ns.route("/folders/<string:folder_id>/restore")
class FolderRestore(Resource):
    @token_required
    def post(self, folder_id: str):
        """
        POST /query-tree/folders/<folder_id>/restore
        Restores folder subtree and ancestors.
        """
        try:
            workspace_id = get_workspace_id_from_header()
            user_id = getattr(g, "user_id", None)
            if not user_id:
                raise ServiceError("Missing user context", status_code=401)
            svc = SavedQueryFolderWriteService(workspace_id=workspace_id, user_id=user_id)
            return svc.restore_folder(folder_id=folder_id), 200
        except ServiceError as e:
            return _handle_service_error(e)
        except Exception:
            logger.exception("Folder restore failed")
            return {"error": "Folder restore failed"}, 500


@tree_ns.route("/folders/<string:folder_id>/purge")
class FolderPurge(Resource):
    @token_required
    def delete(self, folder_id: str):
        """
        DELETE /query-tree/folders/<folder_id>/purge
        Permanently deletes folder subtree (queries then folders).
        """
        try:
            workspace_id = get_workspace_id_from_header()
            user_id = getattr(g, "user_id", None)
            if not user_id:
                raise ServiceError("Missing user context", status_code=401)
            svc = SavedQueryFolderWriteService(workspace_id=workspace_id, user_id=user_id)
            return svc.purge_folder(folder_id=folder_id), 200
        except ServiceError as e:
            return _handle_service_error(e)
        except Exception:
            logger.exception("Folder purge failed")
            return {"error": "Folder purge failed"}, 500

@tree_ns.route("/recent")
class RecentQueries(Resource):
    @token_required
    def get(self):
        """
        GET /query-tree/recent?limit=20
        """
        try:
            workspace_id = get_workspace_id_from_header()
            user_id = getattr(g, "user_id", None)
            is_admin = bool(getattr(g, "is_admin", False))

            if not user_id:
                raise ServiceError("Missing user context", status_code=401)

            limit = request.args.get("limit", 20)
            svc = SavedQueryReadService(workspace_id=workspace_id, user_id=user_id, is_admin=is_admin)
            return svc.fetch_recent_queries(limit=int(limit)), 200
        except ServiceError as e:
            return _handle_service_error(e)
        except Exception:
            logger.exception("Recent queries fetch failed")
            return {"error": "Recent queries fetch failed"}, 500

# -------------------------
# Saved queries
# -------------------------
@saved_query_ns.route("/")
class SavedQueryCreate(Resource):
    @token_required
    def post(self):
        """
        POST /saved-queries
        Body: { "name": "...", "sqlJson": {...}, "description": "...", "folderId": null|folderId }
        """
        try:
            workspace_id = get_workspace_id_from_header()
            user_id = getattr(g, "user_id", None)
            if not user_id:
                raise ServiceError("Missing user context", status_code=401)

            payload = request.get_json(silent=True) or {}
            if not isinstance(payload, dict):
                raise ServiceError("Invalid JSON body", status_code=400)

            name = payload.get("name") or payload.get("title")
            sql_json = payload.get("sqlJson") or payload.get("sql_json")
            description = payload.get("description")
            folder_id = payload.get("folderId")

            svc = SavedQueryWriteService(workspace_id=workspace_id, user_id=user_id)
            return (
                svc.save_query(
                    title=name,
                    sql_json=sql_json,
                    description=description,
                    folder_id=folder_id,
                    query_id=None,
                ),
                200,
            )
        except ServiceError as e:
            return _handle_service_error(e)
        except Exception:
            logger.exception("Saved query create failed")
            return {"error": "Saved query create failed"}, 500


@saved_query_ns.route("/<string:query_id>")
class SavedQuery(Resource):
    @token_required
    def get(self, query_id: str):
        """
        GET /saved-queries/<query_id>
        """
        try:
            workspace_id = get_workspace_id_from_header()
            user_id = getattr(g, "user_id", None)
            is_admin = bool(getattr(g, "is_admin", False))
            if not user_id:
                raise ServiceError("Missing user context", status_code=401)
            svc = SavedQueryReadService(workspace_id=workspace_id, user_id=user_id, is_admin=is_admin)
            return svc.get_query(query_id), 200
        except ServiceError as e:
            return _handle_service_error(e)
        except Exception:
            logger.exception("Saved query read failed")
            return {"error": "Saved query read failed"}, 500

    @token_required
    def patch(self, query_id: str):
        """
        PATCH /saved-queries/<query_id>
        Body: { "name": "...", "sqlJson": {...}, "description": "...", "folderId": null|folderId }
        """
        try:
            workspace_id = get_workspace_id_from_header()
            user_id = getattr(g, "user_id", None)
            if not user_id:
                raise ServiceError("Missing user context", status_code=401)

            payload = request.get_json(silent=True) or {}
            if not isinstance(payload, dict):
                raise ServiceError("Invalid JSON body", status_code=400)

            name = payload.get("name") or payload.get("title")
            sql_json = payload.get("sqlJson") or payload.get("sql_json")
            description = payload.get("description")
            folder_id = payload.get("folderId")

            svc = SavedQueryWriteService(workspace_id=workspace_id, user_id=user_id)
            return (
                svc.save_query(
                    title=name,
                    sql_json=sql_json,
                    description=description,
                    folder_id=folder_id,
                    query_id=query_id,
                ),
                200,
            )
        except ServiceError as e:
            return _handle_service_error(e)
        except Exception:
            logger.exception("Saved query update failed")
            return {"error": "Saved query update failed"}, 500


@saved_query_ns.route("/<string:query_id>/move")
class SavedQueryMove(Resource):
    @token_required
    def patch(self, query_id: str):
        """
        PATCH /saved-queries/<query_id>/move
        Body: { "folderId": null|folderId }
        """
        try:
            workspace_id = get_workspace_id_from_header()
            user_id = getattr(g, "user_id", None)
            payload = request.get_json(silent=True) or {}
            folder_id = (payload.get("folderId") if isinstance(payload, dict) else None)

            if not user_id:
                raise ServiceError("Missing user context", status_code=401)
            svc = SavedQueryWriteService(workspace_id=workspace_id, user_id=user_id)
            return svc.move_query(query_id=query_id, folder_id=folder_id), 200
        except ServiceError as e:
            return _handle_service_error(e)
        except Exception:
            logger.exception("Saved query move failed")
            return {"error": "Saved query move failed"}, 500


@saved_query_ns.route("/<string:query_id>/delete")
class SavedQueryDelete(Resource):
    @token_required
    def post(self, query_id: str):
        """
        POST /saved-queries/<query_id>/delete
        Soft-delete a query.
        """
        try:
            workspace_id = get_workspace_id_from_header()
            user_id = getattr(g, "user_id", None)
            if not user_id:
                raise ServiceError("Missing user context", status_code=401)
            svc = SavedQueryWriteService(workspace_id=workspace_id, user_id=user_id)
            return svc.delete_query(query_id=query_id), 200
        except ServiceError as e:
            return _handle_service_error(e)
        except Exception:
            logger.exception("Saved query delete failed")
            return {"error": "Saved query delete failed"}, 500


@saved_query_ns.route("/<string:query_id>/restore")
class SavedQueryRestore(Resource):
    @token_required
    def post(self, query_id: str):
        """
        POST /saved-queries/<query_id>/restore
        """
        try:
            workspace_id = get_workspace_id_from_header()
            user_id = getattr(g, "user_id", None)
            if not user_id:
                raise ServiceError("Missing user context", status_code=401)
            svc = SavedQueryWriteService(workspace_id=workspace_id, user_id=user_id)
            return svc.restore_query(query_id=query_id), 200
        except ServiceError as e:
            return _handle_service_error(e)
        except Exception:
            logger.exception("Saved query restore failed")
            return {"error": "Saved query restore failed"}, 500


@saved_query_ns.route("/<string:query_id>/purge")
class SavedQueryPurge(Resource):
    @token_required
    def delete(self, query_id: str):
        """
        DELETE /saved-queries/<query_id>/purge
        """
        try:
            workspace_id = get_workspace_id_from_header()
            user_id = getattr(g, "user_id", None)
            if not user_id:
                raise ServiceError("Missing user context", status_code=401)
            svc = SavedQueryWriteService(workspace_id=workspace_id, user_id=user_id)
            return svc.purge_query(query_id=query_id), 200
        except ServiceError as e:
            return _handle_service_error(e)
        except Exception:
            logger.exception("Saved query purge failed")
            return {"error": "Saved query purge failed"}, 500


@saved_query_ns.route("/<string:query_id>/shares")
class SavedQueryShares(Resource):
    @token_required
    @saved_query_ns.marshal_with(share_list_response_model, code=200)
    def get(self, query_id: str):
        """
        GET /saved-queries/<query_id>/shares
        """
        try:
            workspace_id = get_workspace_id_from_header()
            user_id = getattr(g, "user_id", None) or get_user_id()
            if not user_id:
                raise ServiceError("Missing user context", status_code=401)

            svc = SavedQueryShareService(workspace_id=workspace_id, user_id=user_id)
            return svc.list_shares(query_id=query_id), 200
        except ServiceError as e:
            return _handle_service_error(e)
        except Exception:
            logger.exception("Saved query shares fetch failed")
            return {"error": "Saved query shares fetch failed"}, 500

    @token_required
    @saved_query_ns.expect(share_request_model)
    @saved_query_ns.marshal_with(share_response_model, code=200)
    def post(self, query_id: str):
        """
        POST /saved-queries/<query_id>/shares
        Body: { "shareKind": "WORKSPACE|USER", "sharedWithUserId": "<uuid>", "canEdit": false }
        """
        try:
            workspace_id = get_workspace_id_from_header()
            user_id = getattr(g, "user_id", None) or get_user_id()
            if not user_id:
                raise ServiceError("Missing user context", status_code=401)

            payload = request.get_json(silent=True) or {}
            if not isinstance(payload, dict):
                raise ServiceError("Invalid JSON body", status_code=400)

            share_kind = (payload.get("shareKind") or "").strip().upper()
            can_edit = bool(payload.get("canEdit", False))
            if share_kind not in ("WORKSPACE", "USER"):
                raise ServiceError("Invalid shareKind", status_code=400)

            svc = SavedQueryShareService(workspace_id=workspace_id, user_id=user_id)
            if share_kind == "WORKSPACE":
                return svc.share_to_workspace(query_id=query_id, can_edit=can_edit), 200

            shared_with = payload.get("sharedWithUserId")
            if not shared_with:
                raise ServiceError("sharedWithUserId is required", status_code=400)
            return svc.share_to_user(
                query_id=query_id,
                shared_with_user_id=shared_with,
                can_edit=can_edit,
            ), 200
        except ServiceError as e:
            return _handle_service_error(e)
        except Exception:
            logger.exception("Saved query share failed")
            return {"error": "Saved query share failed"}, 500

    @token_required
    @saved_query_ns.expect(share_request_model)
    @saved_query_ns.marshal_with(unshare_response_model, code=200)
    def delete(self, query_id: str):
        """
        DELETE /saved-queries/<query_id>/shares
        Body: { "shareKind": "WORKSPACE|USER", "sharedWithUserId": "<uuid>" }
        """
        try:
            workspace_id = get_workspace_id_from_header()
            user_id = getattr(g, "user_id", None) or get_user_id()
            if not user_id:
                raise ServiceError("Missing user context", status_code=401)

            payload = request.get_json(silent=True) or {}
            if not isinstance(payload, dict):
                raise ServiceError("Invalid JSON body", status_code=400)

            share_kind = (payload.get("shareKind") or "").strip().upper()
            if share_kind not in ("WORKSPACE", "USER"):
                raise ServiceError("Invalid shareKind", status_code=400)
            shared_with = payload.get("sharedWithUserId")

            svc = SavedQueryShareService(workspace_id=workspace_id, user_id=user_id)
            return svc.unshare(
                query_id=query_id,
                share_kind=share_kind,
                shared_with_user_id=shared_with,
            ), 200
        except ServiceError as e:
            return _handle_service_error(e)
        except Exception:
            logger.exception("Saved query unshare failed")
            return {"error": "Saved query unshare failed"}, 500


@saved_query_ns.route("/cohorts/visible")
class VisibleCohorts(Resource):
    @token_required
    def get(self):
        """
        GET /saved-queries/cohorts/visible
        """
        try:
            workspace_id = get_workspace_id_from_header()
            user_id = getattr(g, "user_id", None)
            if not user_id:
                raise ServiceError("Missing user context", status_code=401)

            svc = CohortVisibilityService(workspace_id=workspace_id, user_id=user_id)
            result = svc.list_visible()
            return result, 200
        except ServiceError as e:
            return _handle_service_error(e)
        except Exception:
            logger.exception("Cohort visibility fetch failed")
            return {"error": "Cohort visibility fetch failed"}, 500
