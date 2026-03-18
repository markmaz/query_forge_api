from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from flask import g, request
from flask_restx import Namespace, fields
from app.routes.forge_resource import ForgeResource

from app.decorators.security import token_required
from app.decorators.rbac import require_access
from app.exceptions.forge_error import ForgeError
from app.routes.request_helpers import bool_arg, int_arg
from app.services.semantic.semantic_suggestion_service import SemanticSuggestionService

logger = logging.getLogger(__name__)

semantic_suggestions_ns = Namespace("semantic-suggestions", description="Semantic backfill suggestion endpoints")

run_model = semantic_suggestions_ns.model(
    "SemanticSuggestionRun",
    {
        "id": fields.Integer(readOnly=True),
        "workspace_id": fields.String,
        "vertical": fields.String,
        "status": fields.String,
        "params_json": fields.Raw,
        "total_columns": fields.Integer,
        "processed_columns": fields.Integer,
        "valid_items": fields.Integer,
        "invalid_items": fields.Integer,
        "auto_approved_items": fields.Integer,
        "approved_items": fields.Integer,
        "rejected_items": fields.Integer,
        "applied_items": fields.Integer,
        "failed_apply_items": fields.Integer,
        "error_message": fields.String,
        "created_at": fields.DateTime,
        "updated_at": fields.DateTime,
    },
)

item_patch_model = semantic_suggestions_ns.model(
    "SemanticSuggestionItemPatch",
    {
        "decision_status": fields.String(description="approved|rejected|pending"),
        "decision_reason": fields.String,
    },
)


@semantic_suggestions_ns.route("/runs")
class SuggestionRuns(ForgeResource):
    @token_required
    @require_access("semantic", role="admin")
    @semantic_suggestions_ns.expect(run_model, validate=False)
    def post(self):
        try:
            body: Dict[str, Any] = request.get_json(silent=True) or {}
            created_by = str(getattr(g, "user_id", "") or "") or None
            run = SemanticSuggestionService().create_run(body, created_by=created_by)
            return {"run": run}, 201
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("semantic suggestion run create failed")
            return {"error": "semantic suggestion run create failed"}, 500


@semantic_suggestions_ns.route("/runs/<int:run_id>/execute")
class SuggestionRunExecute(ForgeResource):
    @token_required
    @require_access("semantic", role="admin")
    @semantic_suggestions_ns.doc(params={"llm_id": "Optional workspace LLM id override"})
    def post(self, run_id: int):
        try:
            llm_id = _optional_int(request.args.get("llm_id"), "llm_id")
            run = SemanticSuggestionService().execute_run(run_id, llm_id=llm_id)
            return {"run": run}, 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("semantic suggestion run execute failed")
            return {"error": "semantic suggestion run execute failed"}, 500


@semantic_suggestions_ns.route("/runs/<int:run_id>")
class SuggestionRunById(ForgeResource):
    @token_required
    @require_access("semantic")
    def get(self, run_id: int):
        try:
            run = SemanticSuggestionService().get_run(run_id)
            return {"run": run}, 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("semantic suggestion run get failed")
            return {"error": "semantic suggestion run get failed"}, 500


@semantic_suggestions_ns.route("/items")
class SuggestionItems(ForgeResource):
    @token_required
    @require_access("semantic")
    @semantic_suggestions_ns.doc(
        params={
            "run_id": "Filter by run id",
            "decision_status": "Filter by decision_status",
            "proposed_semantic_type": "Filter by proposed_semantic_type",
            "is_valid": "Filter by item validity",
            "page": "Page number",
            "page_size": "Page size",
        }
    )
    def get(self):
        try:
            run_id = _optional_int(request.args.get("run_id"), "run_id")
            decision_status = request.args.get("decision_status") or None
            proposed_semantic_type = request.args.get("proposed_semantic_type") or None
            is_valid = bool_arg("is_valid", default=None)
            result = SemanticSuggestionService().list_items(
                run_id=run_id,
                decision_status=decision_status,
                proposed_semantic_type=proposed_semantic_type,
                is_valid=is_valid,
                page=int_arg("page", 1),
                page_size=int_arg("page_size", 50),
            )
            return result, 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("semantic suggestion item list failed")
            return {"error": "semantic suggestion item list failed"}, 500


@semantic_suggestions_ns.route("/items/<int:item_id>")
class SuggestionItemById(ForgeResource):
    @token_required
    @require_access("semantic", role="admin")
    @semantic_suggestions_ns.expect(item_patch_model, validate=False)
    def patch(self, item_id: int):
        try:
            body: Dict[str, Any] = request.get_json(silent=True) or {}
            row = SemanticSuggestionService().update_item(item_id, body)
            return {"item": row}, 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("semantic suggestion item patch failed")
            return {"error": "semantic suggestion item patch failed"}, 500


@semantic_suggestions_ns.route("/runs/<int:run_id>/apply")
class SuggestionRunApply(ForgeResource):
    @token_required
    @require_access("semantic", role="admin")
    def post(self, run_id: int):
        try:
            run = SemanticSuggestionService().apply_approved(run_id)
            return {"run": run}, 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("semantic suggestion run apply failed")
            return {"error": "semantic suggestion run apply failed"}, 500


def _optional_int(value: Optional[str], field: str) -> Optional[int]:
    if value is None or str(value).strip() == "":
        return None
    try:
        return int(value)
    except Exception as exc:
        raise ForgeError(f"{field} must be an integer", status_code=400) from exc
