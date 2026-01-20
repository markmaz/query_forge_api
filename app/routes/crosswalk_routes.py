from __future__ import annotations

import io
import logging
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from flask import g, request, send_file
from flask_restx import Namespace, Resource

from app.adapters.databricke_workspace_token_manager import DatabricksWorkspaceTokenManager
from app.adapters.databricks_sql_executor import DatabricksSQLExecutor
from app.adapters.mysql_sql_executor import MySQLSQLExecutor
from app.config import DEFAULT_SQL_WAREHOUSE
from app.decorators.security import token_required
from app.exceptions.service_error import ServiceError
from app.routes._route_utils import get_user_id
from app.services.crosswalks.crosswalk_meta_writer import CrosswalkMetaWriter
from app.services.crosswalks.crosswalk_visibility_service import CrosswalkVisibilityService
from app.services.crosswalks.list_read_service import ListReadService
from app.services.crosswalks.list_template_service import ListTemplateService
from app.services.crosswalks.list_upload_service import ListUploadService
from app.services.crosswalks.list_writer import ListWriter
from app.services.shared.request_context import get_current_username
from app.services.warehouse_service import WarehouseService
from app.services.workspace_service import WorkspaceService

logger = logging.getLogger(__name__)

crosswalk_ns = Namespace("crosswalks", description="Crosswalks (lists + preview + uploads)")


# ----------------------------
# Types / context
# ----------------------------

@dataclass(frozen=True)
class DatabricksContext:
    workspace_id: str
    workspace_url: str
    warehouse_id: str
    user_name: str
    user_id: str
    sql_exec: DatabricksSQLExecutor
    list_writer: ListWriter
    list_reader: ListReadService
    meta_writer: CrosswalkMetaWriter


# ----------------------------
# Small helpers
# ----------------------------

def _to_dict(model):
    """Pydantic v2: model_dump(); v1: dict()."""
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    return model.dict()

def _snake_to_camel(s: str) -> str:
    parts = s.split("_")
    return parts[0] + "".join(p[:1].upper() + p[1:] for p in parts[1:] if p)


def _json_safe(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    if isinstance(value, tuple):
        return [_json_safe(v) for v in value]
    return value


def _camelize(value: Any, *, skip_keys: set[str] | None = None) -> Any:
    if skip_keys is None:
        skip_keys = set()
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, val in value.items():
            if key in skip_keys:
                out[key] = _json_safe(val)
            else:
                out[_snake_to_camel(str(key))] = _camelize(val, skip_keys=skip_keys)
        return out
    if isinstance(value, list):
        return [_camelize(v, skip_keys=skip_keys) for v in value]
    if isinstance(value, tuple):
        return [_camelize(v, skip_keys=skip_keys) for v in value]
    return _json_safe(value)


def _bool_arg(name: str, default: bool = False) -> bool:
    v = (request.args.get(name) or "").strip().lower()
    if not v:
        return default
    return v in ("1", "true", "yes", "y", "on")


def _int_arg(name: str, default: int) -> int:
    v = (request.args.get(name) or "").strip()
    if not v:
        return default
    try:
        return int(v)
    except ValueError:
        raise ServiceError(f"Invalid integer for '{name}'", status_code=400)


def _coerce_bool(value: object, *, field_name: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return int(value) != 0
    if isinstance(value, str):
        v = value.strip().lower()
        if v in ("1", "true", "yes", "y", "on"):
            return True
        if v in ("0", "false", "no", "n", "off"):
            return False
    raise ServiceError(f"{field_name} must be a boolean", status_code=400)


def _get_workspace_id_from_header() -> str:
    workspace_id = (request.headers.get("X-Workspace-Id") or "").strip()
    if not workspace_id:
        raise ServiceError("Missing X-Workspace-Id header", status_code=400)
    return workspace_id


def _resolve_workspace_url(workspace_id: str) -> str:
    ws = WorkspaceService().get_workspace(workspace_id=workspace_id)

    if isinstance(ws, dict):
        url = ws.get("server") or ws.get("host_url") or ws.get("workspace_url")
    else:
        url = (
            getattr(ws, "server", None)
            or getattr(ws, "host_url", None)
            or getattr(ws, "workspace_url", None)
        )

    if not url:
        raise ServiceError(
            f"Workspace '{workspace_id}' did not resolve to a server URL",
            status_code=400,
        )

    return str(url).rstrip("/")


def _resolve_default_warehouse_id(workspace_id: str) -> str:
    wh = WarehouseService().get_warehouse_by_name(
        workspace_id=workspace_id,
        warehouse_name=DEFAULT_SQL_WAREHOUSE,
    )

    warehouse_id = wh.get("warehouse_id") if isinstance(wh, dict) else getattr(wh, "warehouse_id", None)

    if not warehouse_id:
        raise ServiceError(
            f"Default warehouse '{DEFAULT_SQL_WAREHOUSE}' not found for workspace '{workspace_id}'",
            status_code=400,
        )

    return str(warehouse_id)


def _build_databricks_context() -> DatabricksContext:
    workspace_id = _get_workspace_id_from_header()
    workspace_url = _resolve_workspace_url(workspace_id)
    warehouse_id = _resolve_default_warehouse_id(workspace_id)

    user_name = get_current_username()
    user_id = get_user_id()

    token_manager = DatabricksWorkspaceTokenManager(workspace_host=workspace_url)
    sql_exec = DatabricksSQLExecutor(
        base_url=workspace_url,
        token_provider=token_manager,
        default_warehouse_id=warehouse_id,
    )

    list_writer = ListWriter(sql=sql_exec)
    mysql_exec = MySQLSQLExecutor()
    list_reader = ListReadService(mysql=mysql_exec, dbx=sql_exec, workspace_id=workspace_id)
    meta_writer = CrosswalkMetaWriter(mysql_exec)

    return DatabricksContext(
        workspace_id=workspace_id,
        workspace_url=workspace_url,
        warehouse_id=warehouse_id,
        user_name=user_name,
        user_id=user_id,
        sql_exec=sql_exec,
        list_writer=list_writer,
        list_reader=list_reader,
        meta_writer=meta_writer,
    )


def _handle_service_error(e: ServiceError):
    status = getattr(e, "status_code", 400) or 400
    return {"error": str(e)}, status


def _validate_crosswalk_type(crosswalk_type: str) -> str:
    # Keep this centralized so you can later share with swagger models / enums.
    if crosswalk_type not in ("regions", "npiCategories", "serviceLines"):
        raise ServiceError("Invalid type. Must be one of: regions, npiCategories, serviceLines", status_code=400)
    return crosswalk_type


# ----------------------------
# Routes
# ----------------------------

@crosswalk_ns.route("")
class CrosswalkIndex(Resource):
    @token_required
    def get(self):
        """
        GET /crosswalks
        Returns all crosswalk list metadata grouped by type.
        Optional: include_expired=1
        """
        include_expired = _bool_arg("include_expired", default=False)

        try:
            ctx = _build_databricks_context()
            index = ctx.list_reader.get_index(include_expired=include_expired)
            return _camelize(_to_dict(index)), 200

        except ServiceError as e:
            return _handle_service_error(e)
        except Exception:
            logger.exception("Failed to fetch crosswalk index")
            return {"error": "Failed to fetch crosswalks"}, 500


@crosswalk_ns.route("/<string:crosswalk_type>/<string:list_id>/preview")
class CrosswalkPreview(Resource):
    @token_required
    def get(self, crosswalk_type: str, list_id: str):
        """
        GET /crosswalks/<type>/<list_id>/preview?limit=100&offset=0
        Optional: include_expired=1
        """
        include_expired = _bool_arg("include_expired", default=False)
        limit = _int_arg("limit", default=100)
        offset = _int_arg("offset", default=0)

        try:
            crosswalk_type = _validate_crosswalk_type(crosswalk_type)
            ctx = _build_databricks_context()

            details = ctx.list_reader.get_preview_by_id(
                list_type=crosswalk_type,
                list_id=list_id,
                limit=limit,
                offset=offset,
                include_expired=include_expired,
            )
            return _camelize(_to_dict(details), skip_keys={"rows"}), 200

        except ValueError as e:
            return {"error": str(e)}, 404
        except ServiceError as e:
            return _handle_service_error(e)
        except Exception:
            logger.exception("Preview failed type=%s list_id=%s", crosswalk_type, list_id)
            return {"error": "Preview failed"}, 500


@crosswalk_ns.route("/visibility")
class CrosswalkVisibility(Resource):
    @token_required
    def get(self):
        """
        GET /crosswalks/visibility?include_expired=1
        """
        include_expired = _bool_arg("include_expired", default=False)
        try:
            workspace_id = _get_workspace_id_from_header()
            user_id = getattr(g, "user_id", None)
            if not user_id:
                raise ServiceError("Missing user context", status_code=401)

            svc = CrosswalkVisibilityService(workspace_id=workspace_id, user_id=user_id)
            result = svc.get_index(include_expired=include_expired)
            index = _to_dict(result.index)
            for list_type, items in (index or {}).items():
                if not isinstance(items, list):
                    continue
                for item in items:
                    if isinstance(item, dict):
                        item["list_type"] = list_type
            payload = {"index": index, "has_shared": result.has_shared}
            return _camelize(payload), 200
        except ServiceError as e:
            return _handle_service_error(e)
        except Exception:
            logger.exception("Crosswalk visibility fetch failed")
            return {"error": "Crosswalk visibility fetch failed"}, 500


@crosswalk_ns.route("/<string:crosswalk_type>/uploads")
class CrosswalkUpload(Resource):
    @token_required
    def post(self, crosswalk_type: str):
        """
        POST /crosswalks/<type>/uploads
        form-data:
          - file: csv/xlsx
          - list_name: string
        headers:
          - X-Workspace-Id
        """
        try:
            crosswalk_type = _validate_crosswalk_type(crosswalk_type)

            f = request.files.get("file")
            list_name = (request.form.get("list_name") or "").strip()
            is_shared = (request.form.get("is_shared") or "").strip().lower() in ("1", "true", "yes", "y", "on")

            if not f or not f.filename:
                raise ServiceError("file is required", status_code=400)
            if not list_name:
                raise ServiceError("list_name is required", status_code=400)

            ctx = _build_databricks_context()

            svc = ListUploadService(db_writer=ctx.list_writer, meta_writer=ctx.meta_writer)

            result = svc.handle_upload(
                file_bytes=f.read(),
                filename=f.filename,
                list_name=list_name,
                user_name=ctx.user_name,
                workspace_id=ctx.workspace_id,
                user_id=ctx.user_id,
                is_shared=is_shared,
                expected_type=crosswalk_type,
            )

            return result.__dict__, 200

        except ServiceError as e:
            return _handle_service_error(e)
        except Exception:
            logger.exception("Upload failed type=%s", crosswalk_type)
            return {"error": "Upload failed"}, 500
    
@crosswalk_ns.route("/templates/<string:crosswalk_type>")
class CrosswalkTemplateDownload(Resource):
    @token_required
    def get(self, crosswalk_type: str):
        """
        GET /crosswalks/templates/<type>
        type: regions | npiCategories | serviceLines
        optional query param: include_time=1
        """
        include_time = _bool_arg("include_time", default=False)

        try:
            crosswalk_type = _validate_crosswalk_type(crosswalk_type)

            tf = ListTemplateService().generate_template(
                crosswalk_type,  # type: ignore[arg-type]
                include_time=include_time,
            )

            return send_file(
                io.BytesIO(tf.bytes),
                mimetype=tf.content_type,
                as_attachment=True,
                download_name=tf.filename,  # Flask 2.x+
                max_age=0,
            )

        except ValueError as e:
            return {"error": str(e)}, 404
        except ServiceError as e:
            return _handle_service_error(e)
        except Exception:
            logger.exception("Template generation failed type=%s", crosswalk_type)
            return {"error": "Template generation failed"}, 500


@crosswalk_ns.route("/<string:crosswalk_type>/<string:list_id>")
class CrosswalkDetail(Resource):
    @token_required
    def patch(self, crosswalk_type: str, list_id: str):
        """
        PATCH /crosswalks/<type>/<list_id>
        body: { "isShared": true/false }
        """
        try:
            crosswalk_type = _validate_crosswalk_type(crosswalk_type)
            payload = request.get_json(silent=True) or {}
            if "isShared" not in payload:
                raise ServiceError("isShared is required", status_code=400)

            is_shared = _coerce_bool(payload.get("isShared"), field_name="isShared")

            ctx = _build_databricks_context()

            ctx.meta_writer.set_shared(
                workspace_id=ctx.workspace_id,
                list_type=crosswalk_type,
                list_id=list_id,
                is_shared=is_shared,
            )

            return {"listId": list_id, "type": crosswalk_type, "isShared": is_shared}, 200
        except ServiceError as e:
            return _handle_service_error(e)
        except Exception:
            logger.exception("Crosswalk share update failed type=%s list_id=%s", crosswalk_type, list_id)
            return {"error": "Crosswalk share update failed"}, 500

    @token_required
    def delete(self, crosswalk_type: str, list_id: str):
        if crosswalk_type not in ("regions", "npiCategories", "serviceLines"):
            return {"error": "Invalid crosswalk_type"}, 400

        try:
            ctx = _build_databricks_context()

            ctx.list_reader.delete_list(
                list_type=crosswalk_type,  # type: ignore[arg-type]
                list_id=list_id,
            )
            ctx.meta_writer.delete_meta(
                workspace_id=ctx.workspace_id,
                list_type=crosswalk_type,
                list_id=list_id,
            )

            return "", 204

        except ServiceError as e:
            return {"error": str(e)}, getattr(e, "status_code", 400)
        except Exception:
            logger.exception("Delete failed")
            return {"error": "Delete failed"}, 500
