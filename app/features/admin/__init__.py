from .routes import admin_ns, version_ns
from app.api_config import build_url, NAME, VERSION


def register(api):
    api.add_namespace(admin_ns, path=build_url("/", NAME, VERSION, "admin"))
    api.add_namespace(version_ns, path=build_url("/", NAME, VERSION, "version"))
