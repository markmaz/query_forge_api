from app.api_config import build_url, NAME, VERSION
from app.routes.admin_routes import admin_ns
from app.routes.version_routes import version_ns


def register(api):
    api.add_namespace(admin_ns, path=build_url("/", NAME, VERSION, "admin"))
    api.add_namespace(version_ns, path=build_url("/", NAME, VERSION, "version"))
