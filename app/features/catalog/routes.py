from app.api_config import NAME, VERSION, build_url

from .catalog_api import catalog_ns
from .value_override_api import value_override_ns


def register(api):
    api.add_namespace(catalog_ns, path=build_url("/", NAME, VERSION, "catalog"))
    api.add_namespace(value_override_ns, path=build_url("/", NAME, VERSION, "value_overrides"))
