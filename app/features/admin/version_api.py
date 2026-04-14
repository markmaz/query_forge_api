from __future__ import annotations

import logging

from flask_restx import Namespace, Resource

from app.decorators.rbac import public
from app.exceptions.forge_error import ForgeError
from app.features.admin.service import admin_feature_service
from app.services.version_service import VersionService

logger = logging.getLogger(__name__)

version_ns = Namespace("version", description="Application version")


@version_ns.route("/")
class VersionInfo(Resource):
    @public
    def get(self):
        try:
            return admin_feature_service.build_version_service(
                version_service_factory=VersionService
            ).get_version_payload(), 200
        except ForgeError as exc:
            return {"error": str(exc)}, getattr(exc, "status_code", 500) or 500
        except Exception:
            logger.exception("Version fetch failed")
            return {"error": "Version fetch failed"}, 500


__all__ = ["version_ns", "VersionService"]
