from .routes import qf_user_ns, user_workspace_ns, role_ns
from app.api_config import build_url, NAME, VERSION


def register(api):
    api.add_namespace(qf_user_ns, path=build_url("/", NAME, VERSION, "users"))
    api.add_namespace(user_workspace_ns, path=build_url("/", NAME, VERSION, "user-workspaces"))
    api.add_namespace(role_ns, path=build_url("/", NAME, VERSION, "roles"))
