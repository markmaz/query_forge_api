from .rbac_api import rbac_ns
from .role_api import role_ns
from .user_api import qf_user_ns
from .user_workspace_api import user_workspace_ns

NAMESPACES = [
    (qf_user_ns, ("users",)),
    (user_workspace_ns, ("user-workspaces",)),
    (role_ns, ("roles",)),
    (rbac_ns, ("rbac",)),
]
