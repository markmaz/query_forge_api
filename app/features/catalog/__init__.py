from .routes import value_override_ns
from app.api_config import build_url, NAME, VERSION


def register(api):
    api.add_namespace(value_override_ns, path=build_url("/", NAME, VERSION, "value_overrides"))
