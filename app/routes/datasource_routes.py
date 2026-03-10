from __future__ import annotations

import logging

from flask import current_app
from flask_restx import Namespace, fields

from app.decorators.security import token_required
from app.routes.forge_resource import ForgeResource
from app.services.tenancy.datasource_catalog_service import DatasourceCatalogService

logger = logging.getLogger(__name__)

datasource_ns = Namespace("datasources", description="Analytics datasource registry")

_datasource_model = datasource_ns.model(
    "Datasource",
    {
        "name": fields.String(description="Datasource name", example="primary"),
        "type": fields.String(description="SQL dialect / engine type", example="databricks"),
    },
)


@datasource_ns.route("/")
class DatasourceList(ForgeResource):
    """List all registered analytics datasources."""

    @datasource_ns.doc("list_datasources")
    @datasource_ns.response(200, "List of registered datasources", [_datasource_model])
    @datasource_ns.response(401, "Unauthorised")
    @datasource_ns.response(403, "Forbidden")
    @datasource_ns.response(503, "Registry unavailable")
    @token_required
    def get(self):
        """Return all registered analytics datasources.

        Only ``name`` and ``type`` (SQL dialect) are exposed — credentials and
        internal configuration are never included in this response.
        """
        registry = current_app.extensions.get("analytics_registry")
        try:
            db_sources = DatasourceCatalogService().list_datasources(include_inactive=False)
            datasources = [
                {
                    "name": str(row.get("slug") or row.get("name") or f"ds_{row.get('id')}"),
                    "type": row.get("type"),
                }
                for row in db_sources
            ]
            if registry is not None:
                existing = {item["name"] for item in datasources}
                for item in registry.list_datasources():
                    name = str(item.get("name") or "").strip()
                    if not name or name in existing:
                        continue
                    datasources.append({"name": name, "type": item.get("type")})
            if not datasources and registry is None:
                logger.warning("GET /datasources: analytics registry is not available")
                return {"error": "Analytics datasource registry is not available"}, 503
            return datasources, 200
        except Exception:
            logger.exception("GET /datasources: failed to list datasources")
            return {"error": "Failed to retrieve datasources"}, 500
