from app.api_config import NAME, VERSION, build_url
from app.routes.admin_routes import admin_ns

from .version_api import version_ns


def register(api):
    api.add_namespace(admin_ns, path=build_url("/", NAME, VERSION, "admin"))
    api.add_namespace(version_ns, path=build_url("/", NAME, VERSION, "version"))
