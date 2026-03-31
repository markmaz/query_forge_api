from app.routes.admin_routes import admin_ns

from .version_api import version_ns

NAMESPACES = [
    (admin_ns, ("admin",)),
    (version_ns, ("version",)),
]
