from app.api_config import build_url, NAME, VERSION
from app.routes.value_override_routes import value_override_ns


def register(api):
    api.add_namespace(value_override_ns, path=build_url("/", NAME, VERSION, "value_overrides"))
