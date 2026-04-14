from app.api_config import NAME, VERSION

from .routes import NAMESPACES


def register(api):
    for namespace, path in NAMESPACES:
        api.add_namespace(namespace, path=path.format(NAME=NAME, VERSION=VERSION))
