from .workspace_api import workspace_ns
from .workspace_feature_api import workspace_features_ns
from .workspace_llm_api import llm_providers_ns, llm_roles_ns, workspace_llm_ns
from .workspace_table_api import workspace_tables_ns

NAMESPACES = [
    (workspace_ns, ("workspaces",)),
    (workspace_features_ns, ("workspaces",)),
    (workspace_tables_ns, ("workspace-tables",)),
    (llm_roles_ns, ("llm-roles",)),
    (llm_providers_ns, ("llm-providers",)),
    (workspace_llm_ns, tuple()),
]
