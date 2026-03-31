from __future__ import annotations

from app.routes.request_helpers import extract_workspace_id, int_arg, require_user_id


class SkillsFeatureService:
    def extract_workspace_id(self) -> str:
        return extract_workspace_id()

    def int_arg(self, name: str, default: int) -> int:
        return int_arg(name, default)

    def require_user_id(self) -> str:
        return require_user_id()


skills_feature_service = SkillsFeatureService()
