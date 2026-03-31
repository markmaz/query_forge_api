from app.api_config import NAME, VERSION, build_url

from .routes import NAMESPACES


def register(api):
    for namespace, path_parts in NAMESPACES:
        api.add_namespace(namespace, path=build_url("/", NAME, VERSION, *path_parts))
