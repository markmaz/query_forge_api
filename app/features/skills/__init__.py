from .routes import skills_ns, destinations_ns
from app.api_config import build_url, NAME, VERSION


def register(api):
    api.add_namespace(skills_ns, path=build_url("/", NAME, VERSION, "skills"))
    api.add_namespace(destinations_ns, path=build_url("/", NAME, VERSION, "workspaces") + "/<workspace_id>/destinations")
