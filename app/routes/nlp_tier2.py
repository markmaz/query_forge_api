from __future__ import annotations

import logging
from typing import Any, Dict

from flask import request
from flask_restx import Namespace, fields
from flask_restx import Resource

from app.decorators.security import token_required
from app.decorators.rbac import require_access
from app.exceptions.forge_error import ForgeError
from app.nlp.tier2_spacy.pipeline import run_tier2_with_meta
from app.routes.request_helpers import extract_workspace_id

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
    @require_access("ai")
    @nlp_tier2_ns.expect(parse_model, validate=False)
    def post(self):
        body: Dict[str, Any] = request.get_json(silent=True) or {}
        workspace_id = (
            str(body.get("workspaceId") or body.get("workspace_id") or "").strip()
            or extract_workspace_id()
        )
        prompt = str(body.get("prompt") or "").strip()
        if workspace_id == "":
            raise ForgeError("workspaceId is required", status_code=400)
        if prompt == "":
            raise ForgeError("prompt is required", status_code=400)

        payload = run_tier2_with_meta(prompt)
        return {
            "workspaceId": workspace_id,
            "plan_ir": payload["plan_ir"],
            "model": payload["model"],
            "timings_ms": payload["timings_ms"],
        }, 200
