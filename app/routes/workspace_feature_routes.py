from __future__ import annotations

from flask import g, request
from flask_restx import Namespace
from sqlalchemy import text

from app.decorators.rbac import require_admin
from app.decorators.security import token_required
from app.models.rbac import FEATURE_KEYS, Role, UserRole, WorkspaceFeature
from app.routes.forge_resource import ForgeResource
from app.services.rbac_service import set_workspace_feature
from app.services.workspace_service import WorkspaceService
from app.extensions import db

workspace_features_ns = Namespace("workspace-features", description="Workspace feature entitlements")


def _active_workspace_feature_rows(workspace_id: str) -> list[WorkspaceFeature]:
    return WorkspaceFeature.query.filter_by(workspace_id=workspace_id, is_active=True).all()


def _feature_row(workspace_id: str, feature_key: str) -> WorkspaceFeature | None:
    return WorkspaceFeature.query.filter_by(
        workspace_id=workspace_id,
        feature_key=feature_key,
        is_active=True,
    ).first()


def _workspace_readiness_payload(workspace_id: str) -> dict[str, object]:
    enabled = {
        row.feature_key
        for row in _active_workspace_feature_rows(workspace_id)
    }
    has_workspace_admin = (
        db.session.execute(
            text(
                """
                SELECT 1
                FROM user_roles ur
                JOIN roles r
                  ON r.id = ur.role_id
                JOIN workspace_membership wm
                  ON wm.user_id = ur.user_id
                 AND wm.workspace_id = ur.workspace_id
                 AND COALESCE(wm.is_active, 1) = 1
                WHERE r.name = 'workspace_admin'
                  AND ur.workspace_id = :workspace_id
                LIMIT 1
                """
            ),
            {"workspace_id": workspace_id},
        ).first()
        is not None
    )
    super_user_present = (
        UserRole.query.join(Role)
        .filter(Role.name == "super_admin", UserRole.workspace_id.is_(None))
        .first()
        is not None
    )

    completed_steps: list[str] = []
    missing_steps: list[str] = []

    if has_workspace_admin:
        completed_steps.append("workspace_admin")
    else:
        missing_steps.append("workspace_admin")

    if enabled:
        completed_steps.append("workspace_features")
    else:
        missing_steps.append("workspace_features")

    if super_user_present:
        completed_steps.append("super_user")
    else:
        missing_steps.append("super_user")

    workspace_name: str | None = None
    try:
        workspace = WorkspaceService().get_workspace(workspace_id)
        workspace_name = str(workspace.get("workspace_name") or workspace.get("workspace_id") or "").strip() or None
    except Exception:
        workspace_name = None

    return {
        "workspace_id": workspace_id,
        "workspace_name": workspace_name,
        "has_workspace_admin": has_workspace_admin,
        "enabled_feature_count": len(enabled),
        "super_user_present": super_user_present,
        "setup_complete": len(missing_steps) == 0,
        "completed_steps": completed_steps,
        "missing_steps": missing_steps,
    }


@workspace_features_ns.route("/<string:workspace_id>/features")
class WorkspaceFeatureList(ForgeResource):
    @token_required
    @require_admin()
    def get(self, workspace_id: str):
        enabled = {
            row.feature_key
            for row in _active_workspace_feature_rows(workspace_id)
        }
        return {
            "workspace_id": workspace_id,
            "features": [
                {"feature_key": feature_key, "enabled": feature_key in enabled}
                for feature_key in FEATURE_KEYS
            ],
        }, 200

    @token_required
    @require_admin()
    def post(self, workspace_id: str):
        body = request.get_json(silent=True) or {}
        feature_key = str(body.get("feature_key") or "").strip()
        if feature_key not in FEATURE_KEYS:
            return {"error": f"Unknown feature_key: {feature_key}"}, 400

        existing = _feature_row(workspace_id, feature_key)
        if existing:
            return {"error": "Feature already enabled."}, 409

        set_workspace_feature(
            workspace_id=workspace_id,
            feature_key=feature_key,
            is_active=True,
            granted_by=str(getattr(g, "user_id", "") or ""),
        )
        return {"feature_key": feature_key, "enabled": True}, 201


@workspace_features_ns.route("/<string:workspace_id>/features/<string:feature_key>")
class WorkspaceFeatureDetails(ForgeResource):
    @token_required
    @require_admin()
    def delete(self, workspace_id: str, feature_key: str):
        if feature_key not in FEATURE_KEYS:
            return {"error": f"Unknown feature_key: {feature_key}"}, 400

        existing = _feature_row(workspace_id, feature_key)
        if not existing:
            return {"error": "Feature not enabled."}, 404

        set_workspace_feature(
            workspace_id=workspace_id,
            feature_key=feature_key,
            is_active=False,
            granted_by=str(getattr(g, "user_id", "") or ""),
        )
        return {"feature_key": feature_key, "enabled": False}, 200


@workspace_features_ns.route("/<string:workspace_id>/readiness")
class WorkspaceReadiness(ForgeResource):
    @token_required
    @require_admin()
    def get(self, workspace_id: str):
        return _workspace_readiness_payload(workspace_id), 200
