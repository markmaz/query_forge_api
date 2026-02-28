from __future__ import annotations

import logging
from typing import Any, Dict

from flask import request
from flask_restx import Namespace, Resource, fields

from app.decorators.security import token_required
from app.exceptions.service_error import ServiceError
from app.nlp.tier2_spacy.pipeline import run_tier2_with_meta
from app.routes._route_utils import get_workspace_id_from_header, int_arg
from app.services.nlp_review_service import NLPReviewService

logger = logging.getLogger(__name__)

nlp_review_ns = Namespace("nlp-review", description="Tier2 active-learning review queue")

create_model = nlp_review_ns.model(
    "NlpReviewCreate",
    {
        "workspaceId": fields.String(required=False),
        "workspace_id": fields.String(required=False),
        "prompt": fields.String(required=True),
    },
)

patch_model = nlp_review_ns.model(
    "NlpReviewPatch",
    {
        "status": fields.String(required=False, description="pending|approved|rejected"),
        "corrected": fields.Raw(required=False),
    },
)


@nlp_review_ns.route("/review-queue")
class NlpReviewQueue(Resource):
    @token_required
    @nlp_review_ns.expect(create_model, validate=False)
    def post(self):
        try:
            body: Dict[str, Any] = request.get_json(silent=True) or {}
            workspace_id = (
                str(body.get("workspaceId") or body.get("workspace_id") or "").strip()
                or get_workspace_id_from_header()
            )
            prompt = str(body.get("prompt") or "").strip()
            if workspace_id == "":
                raise ServiceError("workspaceId is required", status_code=400)
            if prompt == "":
                raise ServiceError("prompt is required", status_code=400)

            inference = run_tier2_with_meta(prompt)
            service = NLPReviewService()
            item = service.enqueue(
                workspace_id=workspace_id,
                prompt=prompt,
                model_version=str((inference.get("model") or {}).get("version") or "unknown"),
                prediction_json=inference.get("plan_ir") or {},
            )
            return {"row": item}, 201
        except ServiceError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("nlp review queue enqueue failed")
            return {"error": "nlp review queue enqueue failed"}, 500

    @token_required
    def get(self):
        try:
            workspace_id = (
                str(request.args.get("workspaceId") or request.args.get("workspace_id") or "").strip()
                or get_workspace_id_from_header()
            )
            status = request.args.get("status") or None
            limit = int_arg("limit", 50)
            payload = NLPReviewService().list_items(
                workspace_id=workspace_id,
                status=status,
                limit=limit,
            )
            return payload, 200
        except ServiceError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("nlp review queue list failed")
            return {"error": "nlp review queue list failed"}, 500


@nlp_review_ns.route("/review-queue/<int:item_id>")
class NlpReviewQueueItem(Resource):
    @token_required
    @nlp_review_ns.expect(patch_model, validate=False)
    def patch(self, item_id: int):
        try:
            body: Dict[str, Any] = request.get_json(silent=True) or {}
            workspace_id = (
                str(body.get("workspaceId") or body.get("workspace_id") or "").strip()
                or get_workspace_id_from_header()
            )
            item = NLPReviewService().patch_item(
                workspace_id=workspace_id,
                item_id=item_id,
                status=body.get("status"),
                corrected=body.get("corrected") if isinstance(body.get("corrected"), dict) else None,
            )
            return {"row": item}, 200
        except ServiceError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("nlp review queue patch failed")
            return {"error": "nlp review queue patch failed"}, 500


@nlp_review_ns.route("/review-queue/<int:item_id>/approve")
class NlpReviewQueueApprove(Resource):
    @token_required
    def post(self, item_id: int):
        try:
            workspace_id = get_workspace_id_from_header()
            item = NLPReviewService().approve_item(workspace_id=workspace_id, item_id=item_id)
            return {"row": item}, 200
        except ServiceError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("nlp review queue approve failed")
            return {"error": "nlp review queue approve failed"}, 500


@nlp_review_ns.route("/review-queue/<int:item_id>/export")
class NlpReviewQueueExport(Resource):
    @token_required
    def post(self, item_id: int):
        try:
            workspace_id = get_workspace_id_from_header()
            payload = NLPReviewService().export_item_jsonl(workspace_id=workspace_id, item_id=item_id)
            return payload, 200
        except ServiceError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("nlp review queue export failed")
            return {"error": "nlp review queue export failed"}, 500
