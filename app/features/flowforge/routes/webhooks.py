from __future__ import annotations

from flask import request
from flask_restx import Resource

from app.exceptions.forge_error import ForgeError
from app.features.flowforge.routes.common import _service, _webhook_payload, _webhook_token, flowforge_ns, models


@flowforge_ns.route("/webhooks/jotform/<string:webhook_public_id>")
@flowforge_ns.param("webhook_public_id", "Persisted Jotform integration public id created by the integration setup endpoint.")
class FlowForgeJotformWebhook(Resource):
    @flowforge_ns.doc(
        summary="Accept an inbound Jotform webhook",
        description=(
            "Receives Jotform submission notifications for a persisted FlowForge integration. The path "
            "parameter is the generated webhook_public_id returned by POST /integrations/jotform. The supplied "
            "token is hashed and verified against the integration secret hash, then the normalized intake event "
            "is persisted with idempotency. This endpoint intentionally does not require QueryForge bearer "
            "authentication because Jotform calls it as an external webhook."
        ),
        params={
            "token": (
                "Per-integration webhook secret when the provider cannot send custom headers. Prefer the "
                "X-FlowForge-Webhook-Token or X-Jotform-Webhook-Token header when available."
            )
        },
        responses={
            202: ("Webhook accepted and normalized.", models["webhook_accepted"]),
            401: "Webhook token missing or invalid.",
            403: "Integration is disabled.",
            404: "Jotform integration not found.",
            503: "Jotform integration secret is not configured.",
        },
    )
    def post(self, webhook_public_id: str):
        try:
            return (
                _service().accept_jotform_integration_webhook(
                    webhook_public_id=webhook_public_id,
                    payload=_webhook_payload(),
                    token=_webhook_token(),
                    source_ip=request.remote_addr,
                    headers=dict(request.headers),
                ),
                202,
            )
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code

