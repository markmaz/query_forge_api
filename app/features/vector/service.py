from __future__ import annotations

from flask import g

from app.exceptions.forge_error import ForgeError
from app.routes.request_helpers import extract_workspace_id


class VectorFeatureService:
    def extract_workspace_id(self) -> str:
        return extract_workspace_id()

    def require_admin(self) -> None:
        if not bool(getattr(g, "is_admin", False)):
            raise ForgeError("Admin access required", status_code=403)


vector_feature_service = VectorFeatureService()
