from __future__ import annotations

import logging
from typing import Any, Dict

from flask import request
from flask_restx import Namespace, Resource, fields

from app.decorators.security import token_required
from app.exceptions.service_error import ServiceError
from app.nlp.tier2_spacy.pipeline import run_tier2_with_meta
from app.routes._route_utils import get_workspace_id_from_header

logger = logging.getLogger(__name__)

nlp_tier2_ns = Namespace("nlp-tier2", description="Tier2 spaCy parsing")

parse_model = nlp_tier2_ns.model(
    "Tier2ParseRequest",
    {
        "workspaceId": fields.String(required=False),
        "workspace_id": fields.String(required=False),
        "prompt": fields.String(required=True),
    },
)


@nlp_tier2_ns.route("/tier2/parse")
class Tier2Parse(Resource):
    @token_required
    @nlp_tier2_ns.expect(parse_model, validate=False)
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

            payload = run_tier2_with_meta(prompt)
            return {
                "workspaceId": workspace_id,
                "plan_ir": payload["plan_ir"],
                "model": payload["model"],
                "timings_ms": payload["timings_ms"],
            }, 200
        except ServiceError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("tier2 parse failed")
            return {"error": "tier2 parse failed"}, 500
