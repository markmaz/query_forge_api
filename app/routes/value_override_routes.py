from __future__ import annotations

import io
import logging
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from flask import g, request, send_file
from flask_restx import Namespace
from flask_restx import Resource

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.decorators.security import token_required
from app.decorators.rbac import require_access
from app.exceptions.forge_error import ForgeError
from app.ports.sql_executor import ForgeQueryPort
from app.routes.request_helpers import require_user_id
from app.services.value_overrides.value_override_meta_writer import ValueOverrideMetaWriter
from app.services.value_overrides.value_override_visibility_service import ValueOverrideVisibilityService
from app.services.value_overrides.list_read_service import ForgeListReadService
from app.services.value_overrides.list_template_service import ForgeListTemplateService
from app.services.value_overrides.list_upload_service import ForgeListUploadService
from app.services.value_overrides.list_writer import ForgeListWriter
from app.services.workspace_inventory.workspace_context import WorkspaceSqlContextBuilder

logger = logging.getLogger(__name__)

value_override_ns = Namespace("value_overrides", description="ValueOverrides (lists + preview + uploads)")


# ----------------------------
# Types / context
# ----------------------------

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


# ----------------------------
# Small helpers
# ----------------------------

def _to_dict(model):
    """Pydantic v2: model_dump(); v1: dict()."""
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    return model.dict()

def _qf_snake_to_camel(s: str) -> str:
    parts = s.split("_")
    return parts[0] + "".join(p[:1].upper() + p[1:] for p in parts[1:] if p)


def _qf_json_safe(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _qf_json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_qf_json_safe(v) for v in value]
    if isinstance(value, tuple):
        return [_qf_json_safe(v) for v in value]
    return value


def _qf_camelize(value: Any, *, qf_skip_keys: set[str] | None = None) -> Any:
    if qf_skip_keys is None:
        qf_skip_keys = set()
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, val in value.items():
            if key in qf_skip_keys:
                out[key] = _qf_json_safe(val)
            else:
                out[_qf_snake_to_camel(str(key))] = _qf_camelize(val, qf_skip_keys=qf_skip_keys)
        return out
    if isinstance(value, list):
        return [_qf_camelize(v, qf_skip_keys=qf_skip_keys) for v in value]
    if isinstance(value, tuple):
        return [_qf_camelize(v, qf_skip_keys=qf_skip_keys) for v in value]
    return _qf_json_safe(value)


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
        raise ForgeError(f"Invalid integer for '{name}'", status_code=400)


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
    raise ForgeError(f"{field_name} must be a boolean", status_code=400)


def _extract_workspace_id() -> str:
    workspace_id = (request.headers.get("X-Workspace-Id") or "").strip()
    if not workspace_id:
        raise ForgeError("Missing X-Workspace-Id header", status_code=400)
    return workspace_id


def _build_context() -> ValueOverrideContext:
    workspace_id = _extract_workspace_id()
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


def _handle_service_error(e: ForgeError):
    status = getattr(e, "status_code", 400) or 400
    return {"error": str(e)}, status


def _validate_value_override_type(value_override_type: str) -> str:
    # Keep this centralized so you can later share with swagger models / enums.
    if value_override_type not in ("regions", "npiCategories", "serviceLines"):
        raise ForgeError("Invalid type. Must be one of: regions, npiCategories, serviceLines", status_code=400)
    return value_override_type


# ----------------------------
# Routes
# ----------------------------

@value_override_ns.route("")
class ValueOverrideIndex(Resource):
    @token_required
    @require_access("catalog")
    def get(self):
        """
        GET /value_overrides
        Returns all value_override list metadata grouped by type.
        Optional: qf_include_expired=1
        """
        qf_include_expired = _bool_arg("qf_include_expired", default=False)

        try:
            ctx = _build_context()
            index = ctx.qf_list_reader.get_index(qf_include_expired=qf_include_expired)
            return _qf_camelize(_to_dict(index)), 200

        except ForgeError as e:
            return _handle_service_error(e)
        except Exception:
            logger.exception("Failed to fetch value_override index")
            return {"error": "Failed to fetch value_overrides"}, 500


@value_override_ns.route("/<string:value_override_type>/<string:list_id>/preview")
class ValueOverridePreview(Resource):
    @token_required
    @require_access("catalog")
    def get(self, value_override_type: str, list_id: str):
        """
        GET /value_overrides/<type>/<list_id>/preview?limit=100&offset=0
        Optional: qf_include_expired=1
        """
        qf_include_expired = _bool_arg("qf_include_expired", default=False)
        limit = _int_arg("limit", default=100)
        offset = _int_arg("offset", default=0)

        try:
            value_override_type = _validate_value_override_type(value_override_type)
            ctx = _build_context()

            details = ctx.qf_list_reader.get_preview_by_id(
                list_type=value_override_type,
                list_id=list_id,
                limit=limit,
                offset=offset,
                qf_include_expired=qf_include_expired,
            )
            return _qf_camelize(_to_dict(details), qf_skip_keys={"rows"}), 200

        except ForgeError as e:
            return _handle_service_error(e)
        except Exception:
            logger.exception("Preview failed type=%s list_id=%s", value_override_type, list_id)
            return {"error": "Preview failed"}, 500


@value_override_ns.route("/visibility")
class ValueOverrideVisibility(Resource):
    @token_required
    @require_access("catalog")
    def get(self):
        """
        GET /value_overrides/visibility?qf_include_expired=1
        """
        qf_include_expired = _bool_arg("qf_include_expired", default=False)
        try:
            workspace_id = _extract_workspace_id()
            user_id = getattr(g, "user_id", None)
            if not user_id:
                raise ForgeError("Missing user context", status_code=401)

            svc = ValueOverrideVisibilityService(workspace_id=workspace_id, user_id=user_id)
            result = svc.get_index(qf_include_expired=qf_include_expired)
            index = _to_dict(result.index)
            for list_type, items in (index or {}).items():
                if not isinstance(items, list):
                    continue
                for item in items:
                    if isinstance(item, dict):
                        item["list_type"] = list_type
            payload = {"index": index, "has_shared": result.has_shared}
            return _qf_camelize(payload), 200
        except ForgeError as e:
            return _handle_service_error(e)
        except Exception:
            logger.exception("ValueOverride visibility fetch failed")
            return {"error": "ValueOverride visibility fetch failed"}, 500


@value_override_ns.route("/<string:value_override_type>/uploads")
class ValueOverrideUpload(Resource):
    @token_required
    @require_access("catalog")
    def post(self, value_override_type: str):
        """
        POST /value_overrides/<type>/uploads
        form-data:
          - file: csv/xlsx
          - list_name: string
        headers:
          - X-Workspace-Id
        """
        try:
            value_override_type = _validate_value_override_type(value_override_type)

            f = request.files.get("file")
            list_name = (request.form.get("list_name") or "").strip()
            is_shared = (request.form.get("is_shared") or "").strip().lower() in ("1", "true", "yes", "y", "on")

            if not f or not f.filename:
                raise ForgeError("file is required", status_code=400)
            if not list_name:
                raise ForgeError("list_name is required", status_code=400)

            ctx = _build_context()

            svc = ForgeListUploadService(db_writer=ctx.list_writer, meta_writer=ctx.meta_writer)

            result = svc.handle_upload(
                file_bytes=f.read(),
                filename=f.filename,
                list_name=list_name,
                user_name=ctx.user_name,
                workspace_id=ctx.workspace_id,
                user_id=ctx.user_id,
                is_shared=is_shared,
                expected_type=value_override_type,
            )

            return result.__dict__, 200

        except ForgeError as e:
            return _handle_service_error(e)
        except Exception:
            logger.exception("Upload failed type=%s", value_override_type)
            return {"error": "Upload failed"}, 500
    
@value_override_ns.route("/templates/<string:value_override_type>")
class ValueOverrideTemplateDownload(Resource):
    @token_required
    @require_access("catalog")
    def get(self, value_override_type: str):
        """
        GET /value_overrides/templates/<type>
        type: regions | npiCategories | serviceLines
        optional query param: qf_include_time=1
        """
        qf_include_time = _bool_arg("qf_include_time", default=False)

        try:
            value_override_type = _validate_value_override_type(value_override_type)

            tf = ForgeListTemplateService().generate_forge_template(
                value_override_type,  # type: ignore[arg-type]
                qf_include_time=qf_include_time,
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
        except ForgeError as e:
            return _handle_service_error(e)
        except Exception:
            logger.exception("Template generation failed type=%s", value_override_type)
            return {"error": "Template generation failed"}, 500


@value_override_ns.route("/<string:value_override_type>/<string:list_id>")
class ValueOverrideDetail(Resource):
    @token_required
    @require_access("catalog")
    def patch(self, value_override_type: str, list_id: str):
        """
        PATCH /value_overrides/<type>/<list_id>
        body: { "isShared": true/false }
        """
        try:
            value_override_type = _validate_value_override_type(value_override_type)
            payload = request.get_json(silent=True) or {}
            if "isShared" not in payload:
                raise ForgeError("isShared is required", status_code=400)

            is_shared = _coerce_bool(payload.get("isShared"), field_name="isShared")

            ctx = _build_context()
            ctx.qf_list_reader.assert_owner(list_type=value_override_type, list_id=list_id)

            ctx.meta_writer.set_shared(
                workspace_id=ctx.workspace_id,
                list_type=value_override_type,
                list_id=list_id,
                is_shared=is_shared,
            )

            return {"listId": list_id, "type": value_override_type, "isShared": is_shared}, 200
        except ForgeError as e:
            return _handle_service_error(e)
        except Exception:
            logger.exception("ValueOverride share update failed type=%s list_id=%s", value_override_type, list_id)
            return {"error": "ValueOverride share update failed"}, 500

    @token_required
    @require_access("catalog")
    def delete(self, value_override_type: str, list_id: str):
        if value_override_type not in ("regions", "npiCategories", "serviceLines"):
            return {"error": "Invalid value_override_type"}, 400

        try:
            ctx = _build_context()
            ctx.qf_list_reader.assert_owner(
                list_type=value_override_type,  # type: ignore[arg-type]
                list_id=list_id,
            )

            ctx.qf_list_reader.delete_list(
                list_type=value_override_type,  # type: ignore[arg-type]
                list_id=list_id,
            )
            ctx.meta_writer.delete_meta(
                workspace_id=ctx.workspace_id,
                list_type=value_override_type,
                list_id=list_id,
            )

            return "", 204

        except ForgeError as e:
            return {"error": str(e)}, getattr(e, "status_code", 400)
        except Exception:
            logger.exception("Delete failed")
            return {"error": "Delete failed"}, 500
