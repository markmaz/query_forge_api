from __future__ import annotations

import logging
from typing import Any, Dict

from flask import request
from flask_restx import Namespace, Resource

from app.decorators.security import token_required
from app.decorators.rbac import require_access
from app.exceptions.forge_error import ForgeError
from app.services.planner.semantic_extract_service import SemanticExtractService

from .schemas import register_planner_models
from .service import PlannerFeatureService

logger = logging.getLogger(__name__)

planner_ns = Namespace("planner", description="Planner extraction")
extract_model = register_planner_models(planner_ns)["extract_model"]


@planner_ns.route("/extract")
class PlannerExtract(Resource):
    @token_required
    @require_access("planner")
    @planner_ns.expect(extract_model, validate=False)
    def post(self):
        try:
            body: Dict[str, Any] = request.get_json(silent=True) or {}
            prompt = str(body.get("prompt") or "").strip()
            if prompt == "":
                raise ForgeError("prompt is required", status_code=400)

            payload = PlannerFeatureService(
                semantic_extract_service_factory=SemanticExtractService,
            ).extract(prompt)
            return {
                "normalized_text": payload.get("normalized_text"),
                "slots": payload.get("slots") or {},
                "ents": payload.get("ents") or [],
                "by_label": payload.get("by_label") or {},
                "model": payload.get("model") or {},
                "warnings": payload.get("warnings") or [],
            }, 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("planner extract failed")
            return {"error": "planner extract failed"}, 500
