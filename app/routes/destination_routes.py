"""
app/routes/destination_routes.py

Flask-RESTX routes for the Destinations feature.

Endpoints:
    GET    /api/v1/workspaces/<workspace_id>/destinations
    POST   /api/v1/workspaces/<workspace_id>/destinations
    GET    /api/v1/workspaces/<workspace_id>/destinations/<id>
    PUT    /api/v1/workspaces/<workspace_id>/destinations/<id>
    DELETE /api/v1/workspaces/<workspace_id>/destinations/<id>
    POST   /api/v1/workspaces/<workspace_id>/destinations/<id>/test
    GET    /api/v1/workspaces/<workspace_id>/destinations/types

Register in factory.py alongside other route registrations.
Match the pattern in forge_match_routes.py.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from flask import g, request
from flask_restx import Namespace, Resource, fields

from app.decorators.security import token_required
from app.extensions import db
from app.models.destinations import (
    DESTINATION_CONFIG_SCHEMAS,
    DESTINATION_TYPES,
    WorkspaceDestination,
    _count_skills_using_destination,
)
from app.routes.request_helpers import extract_workspace_id

logger = logging.getLogger(__name__)

destinations_ns = Namespace("destinations", description="Workspace Notification Destinations")


# ---------------------------------------------------------------------------
# Swagger models
# ---------------------------------------------------------------------------

destination_create_model = destinations_ns.model("DestinationCreate", {
    "name": fields.String(required=True, example="Finance Alerts"),
    "description": fields.String(example="Slack channel for finance team"),
    "destination_type": fields.String(required=True, enum=list(DESTINATION_TYPES)),
    "config": fields.Raw(required=True, description="Type-specific config — webhook_url, recipients, etc."),
})

destination_update_model = destinations_ns.model("DestinationUpdate", {
    "name": fields.String(),
    "description": fields.String(),
    "config": fields.Raw(),
    "is_active": fields.Boolean(),
})


# ---------------------------------------------------------------------------
# GET /types — available destination types and their config schemas
# ---------------------------------------------------------------------------

@destinations_ns.route("/types")
class DestinationTypeList(Resource):
    @token_required
    def get(self, workspace_id: str = ""):
        """Return all destination types with their config schemas. Available to all users."""
        workspace_id = extract_workspace_id()
        return {
            "destination_types": [
                {
                    "destination_type": dtype,
                    "display_name": _display_name(dtype),
                    "config_schema": DESTINATION_CONFIG_SCHEMAS[dtype],
                }
                for dtype in DESTINATION_TYPES
            ]
        }, 200


# ---------------------------------------------------------------------------
# GET + POST /
# ---------------------------------------------------------------------------

@destinations_ns.route("/")
class DestinationList(Resource):
    @token_required
    def get(self, workspace_id: str = ""):
        """
        List all active destinations for the workspace.
        All users see names + types. Config is masked (sensitive fields as ••••••).
        """
        workspace_id = extract_workspace_id()
        destinations = (
            db.session.query(WorkspaceDestination)
            .filter_by(workspace_id=workspace_id)
            .order_by(WorkspaceDestination.name)
            .all()
        )

        return {
            "destinations": [
                {**d.to_dict(), "usage": d.get_usage_summary()}
                for d in destinations
            ]
        }, 200

    @token_required
    def post(self, workspace_id: str = ""):
        """Create a destination. Admin only."""
        _require_admin()
        workspace_id = extract_workspace_id()
        body = request.json or {}

        dtype = body.get("destination_type")
        if dtype not in DESTINATION_TYPES:
            return {"error": f"Unknown destination_type: {dtype!r}"}, 400

        dest = WorkspaceDestination(
            workspace_id=workspace_id,
            name=body.get("name", "").strip(),
            description=body.get("description", "").strip() or None,
            destination_type=dtype,
            created_by=g.user_id,
        )

        if not dest.name:
            return {"error": "name is required."}, 422

        try:
            dest.set_config(body.get("config", {}))
        except ValueError as exc:
            return {"error": str(exc)}, 422

        db.session.add(dest)
        db.session.commit()

        logger.info(
            "Destination created: id=%s type=%s workspace=%s by user=%s",
            dest.id, dtype, workspace_id, g.user_id,
        )
        return dest.to_dict(), 201


# ---------------------------------------------------------------------------
# GET + PUT + DELETE /<id>
# ---------------------------------------------------------------------------

@destinations_ns.route("/<int:destination_id>")
class DestinationDetail(Resource):
    @token_required
    def get(self, workspace_id: str = "", destination_id: int = 0):
        """Get a single destination. Config is masked."""
        dest = _get_dest_or_404(destination_id)
        return {**dest.to_dict(), "usage": dest.get_usage_summary()}, 200

    @token_required
    def put(self, workspace_id: str = "", destination_id: int = 0):
        """Update a destination. Admin only."""
        _require_admin()
        dest = _get_dest_or_404(destination_id)
        body = request.json or {}

        if "name" in body:
            name = body["name"].strip()
            if not name:
                return {"error": "name cannot be empty."}, 422
            dest.name = name

        if "description" in body:
            dest.description = body["description"].strip() or None

        if "config" in body:
            try:
                # Merge: preserve existing values for fields submitted as "••••••"
                existing = dest.get_config()
                masked_sentinel = "••••••"
                merged = {
                    k: existing.get(k, v) if v == masked_sentinel else v
                    for k, v in body["config"].items()
                }
                # Include existing keys not in the update
                for k, v in existing.items():
                    if k not in merged:
                        merged[k] = v
                dest.set_config(merged)
            except ValueError as exc:
                return {"error": str(exc)}, 422

        if "is_active" in body:
            dest.is_active = body["is_active"]

        dest.updated_by = g.user_id
        db.session.commit()
        return dest.to_dict(), 200

    @token_required
    def delete(self, workspace_id: str = "", destination_id: int = 0):
        """
        Delete a destination. Admin only.
        Blocked if any active skills reference this destination.
        """
        _require_admin()
        dest = _get_dest_or_404(destination_id)
        workspace_id = extract_workspace_id()

        skills_using = _count_skills_using_destination(destination_id, workspace_id)
        if skills_using > 0:
            return {
                "error": f"Cannot delete — used by {skills_using} active skill(s). "
                         f"Deactivate the destination or remove it from those skills first.",
                "skills_using_count": skills_using,
            }, 409

        db.session.delete(dest)
        db.session.commit()
        logger.info("Destination deleted: id=%s workspace=%s by user=%s", destination_id, workspace_id, g.user_id)
        return {"deleted": True, "destination_id": destination_id}, 200


# ---------------------------------------------------------------------------
# POST /<id>/test
# ---------------------------------------------------------------------------

@destinations_ns.route("/<int:destination_id>/test")
class DestinationTest(Resource):
    @token_required
    def post(self, workspace_id: str = "", destination_id: int = 0):
        """
        Send a test message to the destination. Admin only.
        Updates last_tested_at, last_test_status, last_test_message.
        """
        _require_admin()
        dest = _get_dest_or_404(destination_id)

        success, message = _run_test(dest)

        dest.last_tested_at = datetime.now(timezone.utc).replace(tzinfo=None)
        dest.last_test_status = "success" if success else "failed"
        dest.last_test_message = message if not success else None
        db.session.commit()

        return {
            "success": success,
            "message": message,
            "last_tested_at": dest.last_tested_at.isoformat(),
        }, 200 if success else 502


# ---------------------------------------------------------------------------
# Test runner
# ---------------------------------------------------------------------------


def _run_test(dest: WorkspaceDestination) -> tuple[bool, str]:
    """Send a test message via the destination's delivery channel."""
    from app.skills.delivery import DeliveryPayload, get_channel

    try:
        config = dest.get_config()
        dtype = dest.destination_type

        if dtype == "email_group":
            # Use existing mailer directly for email_group test
            from app.email.mailer import get_logo, send_email
            recipients = config.get("recipients", [])
            if not recipients:
                return False, "No recipients configured."
            for recipient in recipients:
                send_email(
                    logo_path=get_logo(),
                    subject="QueryForge — Destination Test",
                    to_email=recipient,
                    html=_test_email_html(dest.name),
                )
            return True, f"Test email sent to {len(recipients)} recipient(s)."

        # Slack, Teams, webhook — use delivery channel
        payload = DeliveryPayload(
            subject=f"QueryForge — Test from '{dest.name}'",
            summary="This is a test message from QueryForge Destinations.",
            detail_html="",
            detail_text=(
                f"✅ *{dest.name}* is configured correctly.\n"
                f"This destination is ready to use in your QueryForge skills."
            ),
            query_name="Test",
            workspace_id=dest.workspace_id,
            query_id=0,
            conditions_failed=[],
            severity="info",
        )
        channel = get_channel(dtype)
        return channel.send(payload, config)

    except Exception as exc:
        logger.exception("Destination test failed for id=%s", dest.id)
        return False, str(exc)


def _test_email_html(dest_name: str) -> str:
    return f"""
<div style="font-family:sans-serif;max-width:480px;margin:0 auto;padding:24px">
  <p style="font-size:14px">
    ✅ <strong>{dest_name}</strong> is configured correctly.
  </p>
  <p style="font-size:13px;color:#666">
    This destination is ready to use in your QueryForge skills.
  </p>
  <p style="font-size:11px;color:#bbb;margin-top:24px">Sent by QueryForge Destinations</p>
</div>"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_dest_or_404(destination_id: int) -> WorkspaceDestination:
    workspace_id = extract_workspace_id()
    dest = (
        db.session.query(WorkspaceDestination)
        .filter_by(id=destination_id, workspace_id=workspace_id)
        .first()
    )
    if not dest:
        destinations_ns.abort(404, f"Destination {destination_id} not found.")
    return dest


def _require_admin() -> None:
    if not getattr(g, "is_admin", False):
        destinations_ns.abort(403, "Admin access required.")


def _display_name(dtype: str) -> str:
    return {
        "slack": "Slack",
        "teams": "Microsoft Teams",
        "webhook": "Generic Webhook",
        "email_group": "Email Group",
    }.get(dtype, dtype.title())
