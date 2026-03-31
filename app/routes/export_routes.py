from __future__ import annotations

import io
import logging
from typing import Optional

import valkey
from flask import request, send_file
from flask_restx import Namespace

from app.config import VALKEY_ADDRESS, VALKEY_PORT
from app.decorators.rbac import require_access
from app.decorators.security import token_required
from app.exceptions.forge_error import ForgeError
from flask_restx import Resource
from app.routes.request_helpers import extract_workspace_id
from app.services.domain_resolver import DomainResolver
from app.services.exports.export_materialization_service import ExportMaterializationService
from app.services.exports.export_policy import (
    QF_EXCEL_MAX_ROWS,
    build_qf_export_policy,
    fetch_cached_rowcount,
    qf_rowcount_signature,
    store_cached_rowcount,
)
from app.services.exports.export_request_service import ExportRequestService
from app.services.exports.export_token_store import ExportTokenStore
from app.services.query_forge_service import QueryForgeService
from app.services.workspace_inventory.workspace_context import WorkspaceSqlContextBuilder

logger = logging.getLogger(__name__)
exports_ns = Namespace("exports", description="Exports")
_EXPORT_TOKEN_TTL_S = 300
_valkey_client: Optional[valkey.StrictValkey] = None


def _abort_with_service_error(e: ForgeError):
    return {"error": str(e)}, getattr(e, "status_code", 400) or 400


def _get_valkey_client() -> valkey.StrictValkey:
    global _valkey_client
    if _valkey_client is None:
        _valkey_client = valkey.StrictValkey(
            host=VALKEY_ADDRESS,
            port=VALKEY_PORT,
            decode_responses=True,
        )
    return _valkey_client


def _build_token_store() -> ExportTokenStore:
    return ExportTokenStore(client_factory=_get_valkey_client, ttl_seconds=_EXPORT_TOKEN_TTL_S)


@exports_ns.route("/excel")
class ExcelExport(Resource):
    @token_required
    @require_access("exports")
    def post(self):
        try:
            workspace_id = extract_workspace_id()
            payload = request.get_json(silent=True) or {}
            result = ExportRequestService(
                workspace_context_builder=WorkspaceSqlContextBuilder(),
                query_forge_service_cls=QueryForgeService,
                domain_resolver_factory=lambda ws: DomainResolver(workspace_id=ws),
                token_store=_build_token_store(),
                fetch_cached_rowcount=fetch_cached_rowcount,
                store_cached_rowcount=store_cached_rowcount,
                build_export_policy=build_qf_export_policy,
                rowcount_signature=qf_rowcount_signature,
                excel_max_rows=QF_EXCEL_MAX_ROWS,
            ).prepare_excel_export(
                workspace_id=workspace_id,
                payload=payload,
            )
            if result.get("error") == "EXCEL_ROW_LIMIT":
                return result, 409
            return result, 200
        except ForgeError as e:
            return _abort_with_service_error(e)
        except Exception:
            logger.exception("Excel export failed")
            return {"error": "Excel export failed"}, 500


@exports_ns.route("/excel/<string:token>")
class ExcelDownload(Resource):
    @token_required
    @require_access("exports")
    def get(self, token: str):
        try:
            workspace_id = extract_workspace_id()
            result = ExportMaterializationService(
                workspace_context_builder=WorkspaceSqlContextBuilder(),
                token_store=_build_token_store(),
            ).build_excel_download(workspace_id=workspace_id, token=token)
            return send_file(
                io.BytesIO(result.content),
                mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                as_attachment=True,
                download_name=result.filename,
                max_age=0,
            )
        except ForgeError as e:
            return _abort_with_service_error(e)
        except Exception:
            logger.exception("Excel download failed")
            return {"error": "Excel download failed"}, 500
