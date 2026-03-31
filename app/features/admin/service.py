from __future__ import annotations

class AdminFeatureService:
    def build_version_service(self, *, version_service_factory):
        return version_service_factory()


admin_feature_service = AdminFeatureService()
