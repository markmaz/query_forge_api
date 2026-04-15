from app.api_config import NAME, VERSION
from app.routes.data_environment import data_environment_ns


def register(api):
    api.add_namespace(data_environment_ns, path=f"/{NAME}/{VERSION}/data-environment")
