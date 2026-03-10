from __future__ import annotations

import logging
from typing import Any, Callable, Dict, Optional, Tuple

from flask import request
from flask_restx import Namespace
from app.routes.forge_resource import ForgeResource

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.decorators.security import token_required
from app.exceptions.forge_error import ForgeError
from app.routes.request_helpers import require_user_id, extract_workspace_id
from app.services.models.model_column_search_service import ModelColumnSearchService
from app.services.models.model_read_service import ModelReadService
from app.services.models.model_sample_read_service import ModelColumnSampleReadService
from app.services.models.model_sample_write_service import ModelSampleService
from app.services.models.model_update_service import ModelUpdateService
from app.services.models.model_upload_service import ModelUploadService
from app.services.shared.jsonify import serialize_record
from app.services.workspace_inventory.workspace_context import WorkspaceContextBuilder

logger = logging.getLogger(__name__)
model_ns = Namespace("models", description="Model (global tables/columns + samples)")


class _RouteServices:
    @staticmethod
    def mysql() -> ForgeMetaSQL:
        return ForgeMetaSQL()

    @staticmethod
    def model_read() -> ModelReadService:
        return ModelReadService(sql=_RouteServices.mysql())

    @staticmethod
    def model_update() -> ModelUpdateService:
        return ModelUpdateService(sql=_RouteServices.mysql())

    @staticmethod
    def model_upload() -> ModelUploadService:
        return ModelUploadService()

    @staticmethod
    def model_search() -> ModelColumnSearchService:
        return ModelColumnSearchService()

    @staticmethod
    def model_sample_reader() -> ModelColumnSampleReadService:
        return ModelColumnSampleReadService()


def _service_error_response(error: ForgeError):
    return {"error": str(error)}, getattr(error, "status_code", 400) or 400


def _run(handler: Callable[[], Tuple[Any, int]], *, log_message: str, client_error: str):
    try:
        return handler()
    except ForgeError as error:
        return _service_error_response(error)
    except Exception:
        logger.exception(log_message)
        return {"error": client_error}, 500


def _json_body() -> Dict[str, Any]:
    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict):
        raise ForgeError("Invalid JSON body", status_code=400)
    return body


def _int_arg(name: str, default: int) -> int:
    raw = (request.args.get(name) or "").strip()
    if not raw:
        return int(default)
    try:
        return int(raw)
    except ValueError:
        raise ForgeError(f"Invalid integer for '{name}'", status_code=400)


def _bool_arg(name: str, default: Optional[bool] = None) -> Optional[bool]:
    raw = (request.args.get(name) or "").strip().lower()
    if raw == "":
        return default
    if raw in {"1", "true", "yes", "y", "on"}:
        return True
    if raw in {"0", "false", "no", "n", "off"}:
        return False
    raise ForgeError(f"Invalid boolean for '{name}'", status_code=400)


def _optional_bool_from_active_arg() -> Optional[bool]:
    raw = (request.args.get("active") or "").strip().lower()
    if raw == "":
        return None
    return raw not in {"0", "false", "no"}


@model_ns.route("/upload")
class ModelUpload(ForgeResource):
    @token_required
    def post(self):
        def handler() -> Tuple[Any, int]:
            workspace_id = extract_workspace_id()
            user_id = require_user_id()
            full_replace = _bool_arg("fullReplace", default=False)

            file = request.files.get("file")
            if not file:
                raise ForgeError("Missing file", status_code=400)

            result = _RouteServices.model_upload().upload(
                workspace_id=workspace_id,
                user_id=user_id,
                file_storage=file,
                full_replace=bool(full_replace),
            )
            return result, 200

        return _run(handler, log_message="Model upload failed", client_error="Model upload failed")


@model_ns.route("/tables")
class ModelTables(ForgeResource):
    @token_required
    def get(self):
        def handler() -> Tuple[Any, int]:
            _ = extract_workspace_id()
            payload = _RouteServices.model_read().list_tables(
                q=(request.args.get("q") or "").strip() or None,
                active=_optional_bool_from_active_arg(),
                limit=_int_arg("limit", 200),
                offset=_int_arg("offset", 0),
            )
            return payload, 200

        return _run(handler, log_message="Model tables fetch failed", client_error="Model tables fetch failed")

    @token_required
    def post(self):
        def handler() -> Tuple[Any, int]:
            _ = extract_workspace_id()
            _ = require_user_id()
            body = _json_body()

            name = body.get("name")
            if not name:
                raise ForgeError("name is required", status_code=400)

            row = _RouteServices.model_update().create_table(
                name=str(name),
                source_table_name=body.get("sourceTableName"),
                description=body.get("description"),
                origin=body.get("origin"),
            )
            return {"row": row}, 201

        return _run(handler, log_message="Model table create failed", client_error="Model table create failed")


@model_ns.route("/tables/<int:table_id>")
class ModelTableById(ForgeResource):
    @token_required
    def patch(self, table_id: int):
        def handler() -> Tuple[Any, int]:
            _ = extract_workspace_id()
            _ = require_user_id()
            body = _json_body()
            row = _RouteServices.model_update().patch_table(
                table_id=int(table_id),
                patch=body,
            )
            return {"row": row}, 200

        return _run(handler, log_message="Model table patch failed", client_error="Model table patch failed")

    @token_required
    def delete(self, table_id: int):
        def handler() -> Tuple[Any, int]:
            _ = extract_workspace_id()
            _ = require_user_id()
            result = _RouteServices.model_update().delete_table(table_id=int(table_id))
            return result, 200

        return _run(handler, log_message="Model table delete failed", client_error="Model table delete failed")


@model_ns.route("/tables/names")
class ModelTableNames(ForgeResource):
    @token_required
    def get(self):
        def handler() -> Tuple[Any, int]:
            _ = extract_workspace_id()
            rows = _RouteServices.model_read().list_table_names(
                q=(request.args.get("q") or "").strip() or None,
                active=_optional_bool_from_active_arg(),
            )
            return {"rows": rows}, 200

        return _run(
            handler,
            log_message="Model table names fetch failed",
            client_error="Model table names fetch failed",
        )


@model_ns.route("/columns")
class ModelColumns(ForgeResource):
    @token_required
    def get(self):
        def handler() -> Tuple[Any, int]:
            _ = extract_workspace_id()
            payload = _RouteServices.model_read().list_columns(
                q=(request.args.get("q") or "").strip() or None,
                table=(request.args.get("table") or "").strip() or None,
                active=_optional_bool_from_active_arg(),
                limit=_int_arg("limit", 1000),
                offset=_int_arg("offset", 0),
                include_table_names=_bool_arg("include_table_names", default=True),
            )
            return payload, 200

        return _run(handler, log_message="Model columns fetch failed", client_error="Model columns fetch failed")

    @token_required
    def post(self):
        def handler() -> Tuple[Any, int]:
            _ = extract_workspace_id()
            user_id = require_user_id()
            body = _json_body()

            table_name = body.get("tableName")
            column_name = body.get("columnName")
            model_table_id = body.get("model_table_id") or body.get("modelTableId")

            if not table_name and model_table_id:
                rows = _RouteServices.mysql().execute_query_mappings(
                    "SELECT name FROM model_table WHERE id = :id LIMIT 1",
                    {"id": model_table_id},
                )
                table_name = rows[0]["name"] if rows else None
                if not table_name:
                    raise ForgeError("model_table_id not found", status_code=404)

            if not table_name or not column_name:
                raise ForgeError("tableName and columnName are required", status_code=400)

            row = _RouteServices.model_update().create_column(
                table_name=table_name,
                column_name=column_name,
                data_type=body.get("dataType"),
                description=body.get("description"),
                is_active=body.get("isActive", True),
                created_by=user_id,
            )
            return {"row": row}, 201

        return _run(handler, log_message="Model column create failed", client_error="Model column create failed")


@model_ns.route("/columns/<int:column_id>")
class ModelColumnById(ForgeResource):
    @token_required
    def patch(self, column_id: int):
        def handler() -> Tuple[Any, int]:
            _ = extract_workspace_id()
            user_id = require_user_id()
            body = _json_body()
            row = _RouteServices.model_update().patch_column(
                column_id=int(column_id),
                patch=body,
                updated_by=user_id,
            )
            return {"row": row}, 200

        return _run(handler, log_message="Model column patch failed", client_error="Model column patch failed")

    @token_required
    def delete(self, column_id: int):
        def handler() -> Tuple[Any, int]:
            _ = extract_workspace_id()
            _ = require_user_id()
            result = _RouteServices.model_update().delete_column(column_id=int(column_id))
            return result, 200

        return _run(handler, log_message="Model column delete failed", client_error="Model column delete failed")


@model_ns.route("/columns/search")
class ModelColumnSearch(ForgeResource):
    @token_required
    def get(self):
        def handler() -> Tuple[Any, int]:
            workspace_id = extract_workspace_id()
            query = (request.args.get("q") or "").strip()
            if len(query) < 3:
                raise ForgeError("Query must be at least 3 characters", status_code=400)

            rows = _RouteServices.model_search().search_columns(
                workspace_id=workspace_id,
                q=query,
                limit=_int_arg("limit", 20),
            )
            return {"rows": rows}, 200

        return _run(handler, log_message="Model column search failed", client_error="Model column search failed")


@model_ns.route("/samples/refresh")
class ModelSamplesRefresh(ForgeResource):
    @token_required
    def post(self):
        def handler() -> Tuple[Any, int]:
            workspace_id = extract_workspace_id()
            schema_name = (request.args.get("schema") or "asset").strip()
            per_table_limit = _int_arg("per_table_limit", 10)

            max_tables_raw = (request.args.get("max_tables") or "").strip()
            max_tables = int(max_tables_raw) if max_tables_raw else None

            ctx = WorkspaceContextBuilder().build(workspace_id)
            result = ModelSampleService(sql=ctx.sql_exec).sync_model_samples(
                workspace_id=workspace_id,
                schema_name=schema_name,
                per_table_limit=per_table_limit,
                max_tables=max_tables,
            )
            return result, 200

        return _run(handler, log_message="Model samples refresh failed", client_error="Model samples refresh failed")


@model_ns.route("/column-sample")
class ModelColumnSample(ForgeResource):
    @token_required
    def get(self):
        def handler() -> Tuple[Any, int]:
            workspace_id = extract_workspace_id()
            user_id = require_user_id()

            domain_id_raw = (request.args.get("domain_id") or "").strip()
            if not domain_id_raw:
                raise ForgeError("domain_id is required", status_code=400)

            workspace_table_id_raw = (request.args.get("workspace_table_id") or "").strip()
            if not workspace_table_id_raw:
                raise ForgeError("workspace_table_id is required", status_code=400)

            column_name = (request.args.get("column_name") or "").strip()
            if not column_name:
                raise ForgeError("column_name is required", status_code=400)

            payload = _RouteServices.model_sample_reader().sample_column_values(
                workspace_id=workspace_id,
                user_id=user_id,
                domain_id=int(domain_id_raw),
                workspace_table_id=int(workspace_table_id_raw),
                column_name=column_name,
                limit=_int_arg("limit", default=10),
            )
            return serialize_record(payload), 200

        return _run(handler, log_message="Model column sample failed", client_error="Model column sample failed")
