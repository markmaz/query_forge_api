from app.routes.admin_routes import admin_ns
from app.routes.version_routes import version_ns

NAMESPACES = [
    (admin_ns, ("admin",)),
    (version_ns, ("version",)),
]
