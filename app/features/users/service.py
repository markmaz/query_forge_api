from __future__ import annotations

from flask import g, request


SENSITIVE_USER_FIELDS = {"password", "otp_secret"}


class UsersFeatureService:
    def build_user_service(self, *, user_service_factory):
        return user_service_factory()

    def build_role_service(self, *, role_service_factory):
        return role_service_factory()

    def public_user_payload(self, user) -> dict:
        return user.model_dump(mode="json", exclude=SENSITIVE_USER_FIELDS)

    def admin_user_scope_workspace_id(self) -> str | None:
        effective_roles = getattr(g, "effective_roles", set()) or set()
        if bool(getattr(g, "is_admin", False)) or "super_admin" in effective_roles:
            return None
        return (request.headers.get("X-Workspace-Id") or "").strip() or None


users_feature_service = UsersFeatureService()
