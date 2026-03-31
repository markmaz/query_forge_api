from app.api_config import NAME, VERSION, build_url
from app.routes.destination_routes import destinations_ns
from app.routes.skills_routes import skills_ns


def register(api):
    api.add_namespace(skills_ns, path=build_url("/", NAME, VERSION, "skills"))
    api.add_namespace(destinations_ns, path=build_url("/", NAME, VERSION, "workspaces") + "/<workspace_id>/destinations")
