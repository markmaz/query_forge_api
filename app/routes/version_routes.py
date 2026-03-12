from __future__ import annotations

import logging

from flask_restx import Namespace

from app.exceptions.forge_error import ForgeError
from app.routes.forge_resource import ForgeResource
from app.services.version_service import VersionService

logger = logging.getLogger(__name__)

version_ns = Namespace("version", description="Application version")


@version_ns.route("/")
class VersionInfo(ForgeResource):
    def get(self):
        try:
            return VersionService().get_version_payload(), 200
        except ForgeError as exc:
            return {"error": str(exc)}, getattr(exc, "status_code", 500) or 500
        except Exception:
            logger.exception("Version fetch failed")
            return {"error": "Version fetch failed"}, 500

