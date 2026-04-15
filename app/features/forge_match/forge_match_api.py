from __future__ import annotations

import io
import logging
from typing import Any, Dict

from flask import request, send_file
from flask_restx import Namespace, fields, Resource
from pydantic import ValidationError

from app.decorators.security import token_required
from app.decorators.rbac import require_access
from app.exceptions.forge_error import ForgeError
from app.routes.request_helpers import extract_workspace_id, int_arg, require_user_id
from app.schemas.forge_match_schema import (
    ForgeMatchAnalyzeRequest,
    ForgeMatchCreateDraftRequest,
    ForgeMatchExecuteDraftSqlRequest,
    ForgeMatchPatchRequest,
)
from app.services.forge_match.mapping_service import ForgeMatchMappingService
from app.services.admin.health_service import AdminHealthService
from app.celery_app import celery
from app.tasks.forge_match_tasks import analyze_forge_match_session_task

logger = logging.getLogger(__name__)

forge_match_ns = Namespace("forge-match", description="ForgeMatch assisted field mapping")

_analyze_model = forge_match_ns.model(
    "ForgeMatchAnalyzeRequest",
    {
        "top_n": fields.Integer(required=False, default=8),
        "domain_id": fields.Integer(required=False),
        "force": fields.Boolean(required=False, default=False),
        "llm_id": fields.Integer(required=False, description="Optional workspace LLM id override"),
    },
)

_patch_item_model = forge_match_ns.model(
    "ForgeMatchPatchItem",
    {
        "mapping_id": fields.String(required=True),
        "action": fields.String(required=False),
        "status": fields.String(required=False),
        "manually_selected_workspace_column_id": fields.Integer(required=False),
        "review_notes": fields.String(required=False),
    },
)

_patch_model = forge_match_ns.model(
    "ForgeMatchPatchRequest",
    {
        "updates": fields.List(fields.Nested(_patch_item_model), required=True),
    },
)

_draft_model = forge_match_ns.model(
    "ForgeMatchCreateDraftRequest",
    {
        "name": fields.String(required=False),
        "include_notes": fields.Boolean(required=False, default=False),
    },
)

_execute_draft_sql_model = forge_match_ns.model(
    "ForgeMatchExecuteDraftSqlRequest",
    {
        "sql": fields.String(required=True),
        "catalog_name": fields.String(required=False),
        "schema_name": fields.String(required=False),
    },
)

_run_job_response = forge_match_ns.model(
    "ForgeMatchAnalyzeJobResponse",
    {
        "job_id": fields.String(required=True),
        "session_id": fields.String(required=True),
        "workspace_id": fields.String(required=True),
        "status": fields.String(required=True),
        "message": fields.String(required=False),
        "source_total": fields.Integer(required=False),
    },
)

_run_status_model = forge_match_ns.model(
    "ForgeMatchAnalyzeRunStatus",
    {
        "id": fields.String(required=True),
        "job_id": fields.String(required=True),
        "session_id": fields.String(required=True),
        "workspace_id": fields.String(required=True),
        "uploaded_filename": fields.String(required=False),
        "status": fields.String(required=True),
        "current_phase": fields.String(required=False),
        "current_source_row_id": fields.String(required=False),
        "source_total": fields.Integer(required=True),
        "source_done": fields.Integer(required=True),
        "source_skipped": fields.Integer(required=True),
        "source_failed": fields.Integer(required=True),
        "progress_pct": fields.Float(required=True),
        "analysis_error": fields.String(required=False),
        "cancel_requested": fields.Boolean(required=True),
        "started_at": fields.String(required=False),
        "completed_at": fields.String(required=False),
        "last_heartbeat_at": fields.String(required=False),
    },
)

_cancel_response_model = forge_match_ns.model(
    "ForgeMatchCancelResponse",
    {
        "job_id": fields.String(required=True),
        "session_id": fields.String(required=True),
        "canceled": fields.Boolean(required=True),
        "status": fields.String(required=True),
        "message": fields.String(required=True),
    },
)


@forge_match_ns.route("")
class ForgeMatchSessionList(Resource):
    @token_required
    @require_access("forge_match")
    @forge_match_ns.doc(
        params={
            "page": "Page number (default 1)",
            "page_size": "Page size (default 25, max 200)",
            "status": "Filter by session status",
            "q": "Search uploaded file name or creator",
        }
    )
    def get(self):
        try:
            workspace_id = extract_workspace_id()
            page = int_arg("page", 1)
            page_size = int_arg("page_size", 25)
            status = (request.args.get("status") or "").strip() or None
            q = (request.args.get("q") or "").strip() or None
            service = ForgeMatchMappingService()
            result = service.list_sessions(
                workspace_id=workspace_id,
                page=page,
                page_size=page_size,
                status=status,
                q=q,
            )
            return result, 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("forge_match list sessions failed")
            return {"error": "forge_match list sessions failed"}, 500


@forge_match_ns.route("/upload")
class ForgeMatchUpload(Resource):
    @token_required
    @require_access("forge_match")
    def post(self):
        try:
            workspace_id = extract_workspace_id()
            user_id = require_user_id()
            uploaded = request.files.get("file")
            if uploaded is None or not uploaded.filename:
                raise ForgeError("file is required", status_code=400)

            service = ForgeMatchMappingService()
            result = service.upload_file(
                workspace_id=workspace_id,
                created_by=user_id,
                filename=str(uploaded.filename),
                file_bytes=uploaded.read(),
            )
            return result, 201
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("forge_match upload failed")
            return {"error": "forge_match upload failed"}, 500


@forge_match_ns.route("/<string:session_id>/analyze")
class ForgeMatchAnalyze(Resource):
    @token_required
    @require_access("forge_match")
    @forge_match_ns.expect(_analyze_model, validate=False)
    def post(self, session_id: str):
        try:
            workspace_id = extract_workspace_id()
            body = request.get_json(silent=True) or {}
            req = ForgeMatchAnalyzeRequest(**body)

            service = ForgeMatchMappingService()
            result = service.analyze_session(
                workspace_id=workspace_id,
                session_id=session_id,
                domain_id=req.domain_id,
                top_n=req.top_n,
                force=req.force,
                llm_id=req.llm_id,
            )
            return result, 200
        except ValidationError as exc:
            return {"error": "invalid request", "details": exc.errors()}, 400
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("forge_match analyze failed")
            return {"error": "forge_match analyze failed"}, 500


@forge_match_ns.route("/<string:session_id>/analyze/start")
class ForgeMatchAnalyzeStart(Resource):
    @token_required
    @require_access("forge_match")
    @forge_match_ns.expect(_analyze_model, validate=False)
    @forge_match_ns.response(202, "Analyze job queued", _run_job_response)
    def post(self, session_id: str):
        try:
            workspace_id = extract_workspace_id()
            body = request.get_json(silent=True) or {}
            req = ForgeMatchAnalyzeRequest(**body)
            service = ForgeMatchMappingService()
            run = service.start_analyze_session_job(
                workspace_id=workspace_id,
                session_id=session_id,
                domain_id=req.domain_id,
                top_n=req.top_n,
                force=req.force,
                llm_id=req.llm_id,
            )

            job_id = str(run["job_id"])
            try:
                with celery.connection_for_write() as conn:
                    conn.ensure_connection(max_retries=0)
                    analyze_forge_match_session_task.apply_async(
                        kwargs={
                            "job_id": job_id,
                            "workspace_id": workspace_id,
                            "session_id": session_id,
                            "top_n": req.top_n,
                            "domain_id": req.domain_id,
                            "force": req.force,
                            "llm_id": req.llm_id,
                        },
                        task_id=job_id,
                        retry=False,
                        connection=conn,
                    )
            except Exception:
                logger.exception(
                    "forge_match analyze async enqueue failed broker_url=%s",
                    str(celery.connection().as_uri() or ""),
                )
                service.mark_enqueue_failed(
                    session_id=session_id,
                    job_id=job_id,
                    source_total=int(run.get("source_total") or 0),
                    error_message="Failed to enqueue ForgeMatch analysis task",
                )
                broker_diag = {}
                try:
                    broker_diag = AdminHealthService().check_broker()
                except Exception:
                    logger.exception("forge_match enqueue failure broker diagnostics failed")
                return {
                    "error": "forge_match analyze queue unavailable",
                    "job_id": job_id,
                    "session_id": session_id,
                    "workspace_id": workspace_id,
                    "broker": broker_diag,
                }, 503

            return run, 202
        except ValidationError as exc:
            return {"error": "invalid request", "details": exc.errors()}, 400
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("forge_match analyze start failed")
            return {"error": "forge_match analyze start failed"}, 500


@forge_match_ns.route("/status/<string:job_id>")
class ForgeMatchAnalyzeStatus(Resource):
    @token_required
    @require_access("forge_match")
    @forge_match_ns.response(200, "Analyze run status", _run_status_model)
    def get(self, job_id: str):
        try:
            workspace_id = extract_workspace_id()
            service = ForgeMatchMappingService()
            result = service.get_analysis_status(workspace_id=workspace_id, job_id=job_id)
            return result, 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("forge_match analyze status failed")
            return {"error": "forge_match analyze status failed"}, 500


@forge_match_ns.route("/cancel/<string:job_id>")
class ForgeMatchAnalyzeCancel(Resource):
    @token_required
    @require_access("forge_match")
    @forge_match_ns.response(200, "Analyze run cancel status", _cancel_response_model)
    def post(self, job_id: str):
        try:
            workspace_id = extract_workspace_id()
            service = ForgeMatchMappingService()
            result = service.cancel_analysis_job(workspace_id=workspace_id, job_id=job_id)
            try:
                analyze_forge_match_session_task.AsyncResult(job_id).revoke(terminate=True, signal="SIGTERM")
            except Exception:
                logger.exception("forge_match analyze revoke failed job_id=%s", job_id)
                result["message"] = "Canceled in DB; task revoke failed"
            return result, 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("forge_match analyze cancel failed")
            return {"error": "forge_match analyze cancel failed"}, 500


@forge_match_ns.route("/history")
class ForgeMatchAnalyzeHistory(Resource):
    @token_required
    @require_access("forge_match")
    @forge_match_ns.doc(params={"limit": "Max rows (default 20, max 200)"})
    @forge_match_ns.response(200, "Analyze run history", [_run_status_model])
    def get(self):
        try:
            workspace_id = extract_workspace_id()
            limit = int_arg("limit", 20)
            service = ForgeMatchMappingService()
            result = service.list_analysis_history(workspace_id=workspace_id, limit=limit)
            return result, 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("forge_match analyze history failed")
            return {"error": "forge_match analyze history failed"}, 500


@forge_match_ns.route("/<string:session_id>")
class ForgeMatchSession(Resource):
    @token_required
    @require_access("forge_match")
    def get(self, session_id: str):
        try:
            workspace_id = extract_workspace_id()
            source_limit = int(request.args.get("source_limit") or 200)
            source_offset = int(request.args.get("source_offset") or 0)
            mapping_limit = int(request.args.get("mapping_limit") or 500)
            mapping_offset = int(request.args.get("mapping_offset") or 0)
            service = ForgeMatchMappingService()
            result = service.get_session(
                workspace_id=workspace_id,
                session_id=session_id,
                source_limit=source_limit,
                source_offset=source_offset,
                mapping_limit=mapping_limit,
                mapping_offset=mapping_offset,
            )
            return result, 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("forge_match session get failed")
            return {"error": "forge_match session get failed"}, 500

    @token_required
    @require_access("forge_match")
    def delete(self, session_id: str):
        try:
            workspace_id = extract_workspace_id()
            service = ForgeMatchMappingService()
            result = service.delete_session(
                workspace_id=workspace_id,
                session_id=session_id,
            )
            return result, 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("forge_match session delete failed")
            return {"error": "forge_match session delete failed"}, 500


@forge_match_ns.route("/<string:session_id>/mappings")
class ForgeMatchMappings(Resource):
    @token_required
    @require_access("forge_match")
    @forge_match_ns.expect(_patch_model, validate=False)
    def patch(self, session_id: str):
        try:
            workspace_id = extract_workspace_id()
            reviewer_user_id = require_user_id()
            body = request.get_json(silent=True) or {}
            req = ForgeMatchPatchRequest(**body)

            service = ForgeMatchMappingService()
            result = service.patch_mappings(
                workspace_id=workspace_id,
                session_id=session_id,
                reviewer_user_id=reviewer_user_id,
                updates=[item.model_dump(mode="json") for item in req.updates],
            )
            return result, 200
        except ValidationError as exc:
            return {"error": "invalid request", "details": exc.errors()}, 400
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("forge_match mappings patch failed")
            return {"error": "forge_match mappings patch failed"}, 500


@forge_match_ns.route("/<string:session_id>/export")
class ForgeMatchExport(Resource):
    @token_required
    @require_access("forge_match")
    def get(self, session_id: str):
        try:
            workspace_id = extract_workspace_id()
            fmt = (request.args.get("format") or "csv").strip().lower()
            service = ForgeMatchMappingService()
            file_bytes, mime_type, filename = service.export_session(
                workspace_id=workspace_id,
                session_id=session_id,
                export_format=fmt,
            )
            return send_file(
                io.BytesIO(file_bytes),
                mimetype=mime_type,
                as_attachment=True,
                download_name=filename,
                max_age=0,
            )
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("forge_match export failed")
            return {"error": "forge_match export failed"}, 500


@forge_match_ns.route("/<string:session_id>/create-view-draft")
class ForgeMatchCreateViewDraft(Resource):
    @token_required
    @require_access("forge_match")
    @forge_match_ns.expect(_draft_model, validate=False)
    def post(self, session_id: str):
        try:
            workspace_id = extract_workspace_id()
            body: Dict[str, Any] = request.get_json(silent=True) or {}
            req = ForgeMatchCreateDraftRequest(**body)
            service = ForgeMatchMappingService()
            result = service.create_view_draft(
                workspace_id=workspace_id,
                session_id=session_id,
                name=req.name,
            )
            return result, 200
        except ValidationError as exc:
            return {"error": "invalid request", "details": exc.errors()}, 400
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("forge_match create view draft failed")
            return {"error": "forge_match create view draft failed"}, 500


@forge_match_ns.route("/<string:session_id>/execute-view-draft-sql")
class ForgeMatchExecuteViewDraftSql(Resource):
    @token_required
    @require_access("forge_match")
    @forge_match_ns.expect(_execute_draft_sql_model, validate=False)
    def post(self, session_id: str):
        try:
            workspace_id = extract_workspace_id()
            body: Dict[str, Any] = request.get_json(silent=True) or {}
            req = ForgeMatchExecuteDraftSqlRequest(**body)
            service = ForgeMatchMappingService()
            result = service.execute_view_draft_sql(
                workspace_id=workspace_id,
                session_id=session_id,
                sql=req.sql,
                catalog_name=req.catalog_name,
                schema_name=req.schema_name,
            )
            return result, 200
        except ValidationError as exc:
            return {"error": "invalid request", "details": exc.errors()}, 400
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("forge_match execute view draft sql failed")
            return {"error": "forge_match execute view draft sql failed"}, 500


@forge_match_ns.route("/<string:session_id>/create-domain-draft")
class ForgeMatchCreateDomainDraft(Resource):
    @token_required
    @require_access("forge_match")
    @forge_match_ns.expect(_draft_model, validate=False)
    def post(self, session_id: str):
        try:
            workspace_id = extract_workspace_id()
            body: Dict[str, Any] = request.get_json(silent=True) or {}
            req = ForgeMatchCreateDraftRequest(**body)
            service = ForgeMatchMappingService()
            result = service.create_domain_draft(
                workspace_id=workspace_id,
                session_id=session_id,
                name=req.name,
            )
            return result, 200
        except ValidationError as exc:
            return {"error": "invalid request", "details": exc.errors()}, 400
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("forge_match create domain draft failed")
            return {"error": "forge_match create domain draft failed"}, 500


__all__ = ["forge_match_ns"]
