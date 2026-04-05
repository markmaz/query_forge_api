from __future__ import annotations

import logging

from flask_restx import Namespace

from app.decorators.rbac import public
from flask_restx import Resource
from app.services.version_service import VersionService

logger = logging.getLogger(__name__)

version_ns = Namespace("version", description="Application version")


@version_ns.route("/")
class VersionInfo(Resource):
    @public
    def get(self):
        return VersionService().get_version_payload(), 200

