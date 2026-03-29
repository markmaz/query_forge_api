from app.api_config import build_url, NAME, VERSION
from app.routes.rbac_routes import rbac_ns
from app.routes.role_routes import role_ns
from app.routes.user_routes import qf_user_ns
from app.routes.user_workspace_routes import user_workspace_ns


def register(api):
    api.add_namespace(qf_user_ns, path=build_url("/", NAME, VERSION, "users"))
    api.add_namespace(user_workspace_ns, path=build_url("/", NAME, VERSION, "user-workspaces"))
    api.add_namespace(role_ns, path=build_url("/", NAME, VERSION, "roles"))
    api.add_namespace(rbac_ns, path=build_url("/", NAME, VERSION, "rbac"))
