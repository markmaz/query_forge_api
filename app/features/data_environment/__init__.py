from .routes import data_environment_ns
from app.api_config import NAME, VERSION


def register(api):
    api.add_namespace(data_environment_ns, path=f"/{NAME}/{VERSION}/data-environment")
