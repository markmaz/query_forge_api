from __future__ import annotations

import logging

from flask import request
from flask_restx import Namespace, Resource

from app.adapters.mysql_sql_executor import MySQLSQLExecutor
from app.decorators.security import token_required
from app.exceptions.service_error import ServiceError
from app.routes._route_utils import bool_arg, get_user_id, get_workspace_id_from_header, int_arg
from app.services.models.model_column_search_service import ModelColumnSearchService
from app.services.models.model_read_service import ModelReadService
from app.services.models.model_sample_read_service import ModelColumnSampleReadService
from app.services.models.model_sample_write_service import ModelSampleService
from app.services.models.model_update_service import ModelUpdateService
from app.services.models.model_upload_service import ModelUploadService
from app.services.shared.jsonify import jsonify_dict
from app.services.workspace_inventory.workspace_context import WorkspaceContextBuilder

logger = logging.getLogger(__name__)
model_ns = Namespace("models", description="Model (global tables/columns + samples)")


def _handle_service_error(e: ServiceError):
    return {"error": str(e)}, getattr(e, "status_code", 400) or 400


# ----------------------------
# Upload
# ----------------------------

@model_ns.route("/upload")
class ModelUpload(Resource):
    @token_required
    def post(self):
        """
        POST /model/upload?fullReplace=true|false
        multipart/form-data: file=<csv>
        headers: X-Workspace-Id, X-User-Id (optional)
        """
        try:
            workspace_id = get_workspace_id_from_header()
            user_id = get_user_id()

            full_replace = bool_arg("fullReplace", default=False)

            file = request.files.get("file")
            if not file:
                raise ServiceError("Missing file", status_code=400)

            res = ModelUploadService().upload(
                workspace_id=workspace_id,
                user_id=user_id,
                file_storage=file,
                full_replace=bool(full_replace),
            )
            return res, 200

        except ServiceError as e:
            return _handle_service_error(e)
        except Exception:
            logger.exception("Model upload failed")
            return {"error": "Model upload failed"}, 500


# ----------------------------
# Tables
# ----------------------------

# app/routes/model_routes.py

@model_ns.route("/tables")
class ModelTables(Resource):
    @token_required
    def get(self):
        """
        GET /model/tables?q=&active=&limit=&offset=
        """
        try:
            _ = get_workspace_id_from_header()

            q = (request.args.get("q") or "").strip() or None

            active_s = (request.args.get("active") or "").strip().lower()
            active = None if active_s == "" else active_s not in ("0", "false", "no")

            limit = int_arg("limit", 200)
            offset = int_arg("offset", 0)

            # ✅ list_tables already returns {rows,total,limit,offset}
            payload = ModelReadService(sql=MySQLSQLExecutor()).list_tables(
                q=q, active=active, limit=limit, offset=offset
            )
            return payload, 200

        except ServiceError as e:
            return _handle_service_error(e)
        except Exception:
            logger.exception("Model tables fetch failed")
            return {"error": "Model tables fetch failed"}, 500


@model_ns.route("/tables/names")
class ModelTableNames(Resource):
    @token_required
    def get(self):
        """
        GET /model/tables/names?q=&active=
        Small payload for dropdowns/autocomplete.
        """
        try:
            _ = get_workspace_id_from_header()

            q = (request.args.get("q") or "").strip() or None

            active_s = (request.args.get("active") or "").strip().lower()
            active = None if active_s == "" else active_s not in ("0", "false", "no")

            # ✅ service now supports q
            rows = ModelReadService(sql=MySQLSQLExecutor()).list_table_names(q=q, active=active)
            return {"rows": rows}, 200

        except ServiceError as e:
            return _handle_service_error(e)
        except Exception:
            logger.exception("Model table names fetch failed")
            return {"error": "Model table names fetch failed"}, 500


@model_ns.route("/columns")
class ModelColumns(Resource):
    @token_required
    def get(self):
        """
        GET /model/columns?table=&q=&active=&limit=&offset=&include_table_names=
        """
        try:
            _ = get_workspace_id_from_header()

            table = (request.args.get("table") or "").strip() or None
            q = (request.args.get("q") or "").strip() or None

            active_s = (request.args.get("active") or "").strip().lower()
            active = None if active_s == "" else active_s not in ("0", "false", "no")

            limit = int_arg("limit", 1000)
            offset = int_arg("offset", 0)
            include_table_names = bool_arg("include_table_names", default=True)

            payload = ModelReadService(sql=MySQLSQLExecutor()).list_columns(
                q=q,
                table=table,
                active=active,
                limit=limit,
                offset=offset,
                include_table_names=include_table_names,
            )
            return payload, 200

        except ServiceError as e:
            return _handle_service_error(e)
        except Exception:
            logger.exception("Model columns fetch failed")
            return {"error": "Model columns fetch failed"}, 500

    @token_required
    def post(self):
        """
        POST /model/columns
        Body: { tableName | model_table_id, columnName, dataType?, description?, isActive? }
        """
        try:
            _ = get_workspace_id_from_header()
            user_id = get_user_id()

            body = request.get_json(silent=True) or {}
            if not isinstance(body, dict):
                raise ServiceError("Invalid JSON body", status_code=400)

            table_name = body.get("tableName")
            column_name = body.get("columnName")
            model_table_id = body.get("model_table_id") or body.get("modelTableId")

            if not table_name and model_table_id:
                rows = MySQLSQLExecutor().execute_query_mappings(
                    "SELECT name FROM model_table WHERE id = :id LIMIT 1",
                    {"id": model_table_id},
                )
                table_name = rows[0]["name"] if rows else None
                if not table_name:
                    raise ServiceError("model_table_id not found", status_code=404)

            if not table_name or not column_name:
                raise ServiceError("tableName and columnName are required", status_code=400)

            row = ModelUpdateService(sql=MySQLSQLExecutor()).create_column(
                table_name=table_name,
                column_name=column_name,
                data_type=body.get("dataType"),
                description=body.get("description"),
                is_active=body.get("isActive", True),
                created_by=user_id,
            )
            return {"row": row}, 201

        except ServiceError as e:
            return _handle_service_error(e)
        except Exception:
            logger.exception("Model column create failed")
            return {"error": "Model column create failed"}, 500


@model_ns.route("/columns/<int:column_id>")
class ModelColumnById(Resource):
    @token_required
    def patch(self, column_id: int):
        """
        PATCH /model/columns/<id>
        Body: { description?, dataType?, isActive? }
        """
        try:
            _ = get_workspace_id_from_header()
            user_id = get_user_id()

            body = request.get_json(silent=True) or {}
            if not isinstance(body, dict):
                raise ServiceError("Invalid JSON body", status_code=400)

            row = ModelUpdateService(sql=MySQLSQLExecutor()).patch_column(
                column_id=int(column_id),
                patch=body,
                updated_by=user_id,
            )
            return {"row": row}, 200

        except ServiceError as e:
            return _handle_service_error(e)
        except Exception:
            logger.exception("Model column patch failed")
            return {"error": "Model column patch failed"}, 500


@model_ns.route("/columns/search")
class ModelColumnSearch(Resource):
    @token_required
    def get(self):
        """
        GET /model/columns/search?q=&limit=
        Type-ahead search on model_column.column_name (workspace scoped).
        """
        try:
            workspace_id = get_workspace_id_from_header()

            q = (request.args.get("q") or "").strip()
            if len(q) < 3:
                raise ServiceError("Query must be at least 3 characters", status_code=400)

            limit = int_arg("limit", 20)
            rows = ModelColumnSearchService().search_columns(
                workspace_id=workspace_id,
                q=q,
                limit=limit,
            )
            return {"rows": rows}, 200

        except ServiceError as e:
            return _handle_service_error(e)
        except Exception:
            logger.exception("Model column search failed")
            return {"error": "Model column search failed"}, 500


# ----------------------------
# Samples (Option 2 - stored on model_table)
# ----------------------------

@model_ns.route("/samples/refresh")
class ModelSamplesRefresh(Resource):
    @token_required
    def post(self):
        """
        POST /model/samples/refresh?schema=asset&max_tables=200&per_table_limit=10
        Uses WorkspaceContextBuilder (DBX executor) but writes samples onto model_table.
        """
        try:
            workspace_id = get_workspace_id_from_header()
            schema_name = (request.args.get("schema") or "asset").strip()
            per_table_limit = int_arg("per_table_limit", 10)
            max_tables = request.args.get("max_tables")
            max_tables_i = int(max_tables) if (max_tables or "").strip() else None

            ctx = WorkspaceContextBuilder().build(workspace_id)
            res = ModelSampleService(sql=ctx.sql_exec).sync_model_samples(
                workspace_id=workspace_id,
                schema_name=schema_name,
                per_table_limit=per_table_limit,
                max_tables=max_tables_i,
            )
            return res, 200

        except ServiceError as e:
            return _handle_service_error(e)
        except Exception:
            logger.exception("Model samples refresh failed")
            return {"error": "Model samples refresh failed"}, 500

@model_ns.route("/column-sample")
class ModelColumnSample(Resource):
    @token_required
    def get(self):
        """
        GET /models/column-sample?domain_id=&workspace_table_id=&column_name=&limit=10
        headers:
          - X-Workspace-Id
        """
        try:
            workspace_id = get_workspace_id_from_header()
            user_id = get_user_id()

            domain_id = request.args.get("domain_id")
            if not (domain_id or "").strip():
                raise ServiceError("domain_id is required", status_code=400)

            wtid = request.args.get("workspace_table_id")
            if not (wtid or "").strip():
                raise ServiceError("workspace_table_id is required", status_code=400)

            column_name = (request.args.get("column_name") or "").strip()
            if not column_name:
                raise ServiceError("column_name is required", status_code=400)

            limit = int_arg("limit", default=10)

            svc = ModelColumnSampleReadService()
            payload = svc.sample_column_values(
                workspace_id=workspace_id,
                user_id=user_id,
                domain_id=int(domain_id),
                workspace_table_id=int(wtid),
                column_name=column_name,
                limit=limit,
            )

            return jsonify_dict(payload), 200

        except ServiceError as e:
            return {"error": str(e)}, getattr(e, "status_code", 400) or 400
        except Exception:
            logger.exception("Model column sample failed")
            return {"error": "Model column sample failed"}, 500
