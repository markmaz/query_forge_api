from .routes import product_ns, product_group_ns, value_override_ns
from app.api_config import build_url, NAME, VERSION


def register(api):
    api.add_namespace(product_ns, path=build_url("/", NAME, VERSION, "products"))
    api.add_namespace(product_group_ns, path=build_url("/", NAME, VERSION, "product-groups"))
    api.add_namespace(value_override_ns, path=build_url("/", NAME, VERSION, "value_overrides"))
