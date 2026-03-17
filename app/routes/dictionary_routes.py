from __future__ import annotations

import io
import logging

import pandas as pd
from flask import request
from flask_restx import Namespace
from app.routes.forge_resource import ForgeResource

from app.decorators.security import token_required
from app.exceptions.forge_error import ForgeError
from app.services.dictionary.dictionary_service import DictionaryService

logger = logging.getLogger(__name__)

_MAX_IMPORT_BYTES = 10 * 1024 * 1024  # 10 MB

dictionary_ns = Namespace("dictionary", description="Data dictionary (workspace layer)")


def _parse_int(raw: str | None, default: int, name: str = "parameter") -> int:
    """Parse an int query param, raising ForgeError(400) on non-numeric input."""
    val = (raw or "").strip()
    if not val:
        return default
    try:
        return int(val)
    except ValueError:
        raise ForgeError(f"Invalid integer for {name}: {val!r}", status_code=400)


def _workspace_id() -> str:
    ws = (request.headers.get("X-Workspace-Id") or "").strip()
    if not ws:
        raise ForgeError("X-Workspace-Id header is required", status_code=400)
    return ws


def _error(exc: ForgeError):
    return {"error": str(exc)}, getattr(exc, "status_code", 400) or 400


def _parse_file(file_storage) -> list[dict]:
    """Parse CSV or Excel upload into list of dicts with normalized column names."""
    filename = file_storage.filename or ""
    content = file_storage.read()
    if len(content) > _MAX_IMPORT_BYTES:
        raise ForgeError(
            f"File too large: max {_MAX_IMPORT_BYTES // (1024 * 1024)} MB", status_code=413
        )
    bio = io.BytesIO(content)

    lower = filename.lower()
    try:
        if lower.endswith(".csv"):
            df = pd.read_csv(bio, dtype=str, keep_default_na=False)
        elif lower.endswith((".xlsx", ".xls")):
            df = pd.read_excel(bio, dtype=str, keep_default_na=False)
        else:
            raise ForgeError("Unsupported file type — use .csv or .xlsx", status_code=400)
    except ForgeError:
        raise
    except Exception as exc:
        raise ForgeError(f"File parse error: {exc}", status_code=400) from exc

    # Normalize column headers
    df.columns = [str(c).strip().lower() for c in df.columns]

    for required in ("table_name", "column_name"):
        if required not in df.columns:
            raise ForgeError(
                f"File is missing required column: {required}", status_code=400
            )

    return df.to_dict(orient="records")


# ---------------------------------------------------------------------------
# /tables
# ---------------------------------------------------------------------------

@dictionary_ns.route("/tables")
class DictionaryTables(ForgeResource):
    @token_required
    def get(self):
        try:
            workspace_id = _workspace_id()
            q = (request.args.get("q") or "").strip() or None
            limit = _parse_int(request.args.get("limit"), 500, "limit")
            offset = _parse_int(request.args.get("offset"), 0, "offset")
            result = DictionaryService().list_tables(
                workspace_id=workspace_id, q=q, limit=limit, offset=offset
            )
            return result, 200
        except ForgeError as exc:
            return _error(exc)
        except Exception:
            logger.exception("GET /dictionary/tables failed")
            return {"error": "Failed to fetch tables"}, 500


# ---------------------------------------------------------------------------
# /tables/:id  (PATCH)
# ---------------------------------------------------------------------------

@dictionary_ns.route("/tables/<int:table_id>")
class DictionaryTableDetail(ForgeResource):
    @token_required
    def patch(self, table_id: int):
        try:
            workspace_id = _workspace_id()
            body = request.get_json(silent=True) or {}
            patch = {}
            if "description" in body:
                patch["description"] = body["description"]
            if not patch:
                raise ForgeError("No patchable fields in request body", status_code=400)
            result = DictionaryService().patch_table(
                workspace_id=workspace_id, table_id=table_id, patch=patch
            )
            return result, 200
        except ForgeError as exc:
            return _error(exc)
        except Exception:
            logger.exception("PATCH /dictionary/tables/%s failed", table_id)
            return {"error": "Failed to update table"}, 500


# ---------------------------------------------------------------------------
# /columns  and  /columns/search
# ---------------------------------------------------------------------------

@dictionary_ns.route("/columns")
class DictionaryColumns(ForgeResource):
    @token_required
    def get(self):
        try:
            workspace_id = _workspace_id()
            wtid_raw = (request.args.get("workspace_table_id") or "").strip()
            if not wtid_raw:
                raise ForgeError("workspace_table_id is required", status_code=400)
            workspace_table_id = _parse_int(wtid_raw, 0, "workspace_table_id")
            q = (request.args.get("q") or "").strip() or None
            active_only_raw = (request.args.get("active_only") or "true").strip().lower()
            active_only = active_only_raw not in ("false", "0", "no")
            result = DictionaryService().list_columns(
                workspace_id=workspace_id,
                workspace_table_id=workspace_table_id,
                q=q,
                active_only=active_only,
            )
            return result, 200
        except ForgeError as exc:
            return _error(exc)
        except Exception:
            logger.exception("GET /dictionary/columns failed")
            return {"error": "Failed to fetch columns"}, 500


@dictionary_ns.route("/columns/search")
class DictionaryColumnsSearch(ForgeResource):
    @token_required
    def get(self):
        try:
            workspace_id = _workspace_id()
            q = (request.args.get("q") or "").strip()
            if not q:
                raise ForgeError("q is required", status_code=400)
            limit = _parse_int(request.args.get("limit"), 200, "limit")
            active_only_raw = (request.args.get("active_only") or "true").strip().lower()
            active_only = active_only_raw not in ("false", "0", "no")
            result = DictionaryService().search_columns(
                workspace_id=workspace_id, q=q, limit=limit, active_only=active_only
            )
            return result, 200
        except ForgeError as exc:
            return _error(exc)
        except Exception:
            logger.exception("GET /dictionary/columns/search failed")
            return {"error": "Failed to search columns"}, 500


# ---------------------------------------------------------------------------
# /columns/:id  (PATCH)
# ---------------------------------------------------------------------------

@dictionary_ns.route("/columns/<int:column_id>")
class DictionaryColumn(ForgeResource):
    @token_required
    def patch(self, column_id: int):
        try:
            workspace_id = _workspace_id()
            body = request.get_json(silent=True) or {}
            patch = {}
            if "description" in body:
                patch["description"] = body["description"]
            if "data_type" in body:
                patch["data_type"] = body["data_type"]
            if "is_active" in body:
                patch["is_active"] = bool(body["is_active"])
            if "semantic_type" in body:
                patch["semantic_type"] = body["semantic_type"] or None
            if "semantic_entity" in body:
                patch["semantic_entity"] = body["semantic_entity"] or None
            if "semantic_sub_type" in body:
                patch["semantic_sub_type"] = body["semantic_sub_type"] or None
            if "semantic_confidence" in body:
                raw = body["semantic_confidence"]
                patch["semantic_confidence"] = float(raw) if raw is not None else None
            if not patch:
                raise ForgeError("No patchable fields in request body", status_code=400)
            result = DictionaryService().patch_column(
                workspace_id=workspace_id, column_id=column_id, patch=patch
            )
            return result, 200
        except ForgeError as exc:
            return _error(exc)
        except Exception:
            logger.exception("PATCH /dictionary/columns/%s failed", column_id)
            return {"error": "Failed to update column"}, 500


# ---------------------------------------------------------------------------
# /columns/import  (POST)
# ---------------------------------------------------------------------------

@dictionary_ns.route("/columns/import")
class DictionaryColumnsImport(ForgeResource):
    @token_required
    def post(self):
        try:
            workspace_id = _workspace_id()
            full_replace_raw = (request.args.get("fullReplace") or "false").strip().lower()
            full_replace = full_replace_raw in ("true", "1", "yes")

            file_storage = request.files.get("file")
            if not file_storage:
                raise ForgeError("file is required", status_code=400)

            rows = _parse_file(file_storage)

            if full_replace and not rows:
                raise ForgeError(
                    "Cannot use fullReplace with an empty file", status_code=400
                )

            result = DictionaryService().import_columns(
                workspace_id=workspace_id, rows=rows, full_replace=full_replace
            )
            return result, 200
        except ForgeError as exc:
            return _error(exc)
        except Exception:
            logger.exception("POST /dictionary/columns/import failed")
            return {"error": "Import failed"}, 500
