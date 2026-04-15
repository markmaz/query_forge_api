from app.api_config import NAME, VERSION, build_url
from app.features.users.rbac_api import rbac_ns
from app.features.users.role_api import role_ns
from app.features.users.user_api import qf_user_ns
from app.features.users.user_workspace_api import user_workspace_ns


def register(api):
    api.add_namespace(qf_user_ns, path=build_url("/", NAME, VERSION, "users"))
    api.add_namespace(user_workspace_ns, path=build_url("/", NAME, VERSION, "user-workspaces"))
    api.add_namespace(role_ns, path=build_url("/", NAME, VERSION, "roles"))
    api.add_namespace(rbac_ns, path=build_url("/", NAME, VERSION, "rbac"))
