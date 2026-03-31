from app.routes.workspace_feature_routes import workspace_features_ns
from app.routes.workspace_llm_routes import llm_providers_ns, llm_roles_ns, workspace_llm_ns
from app.routes.workspace_routes import workspace_ns
from app.routes.workspace_table_routes import workspace_tables_ns

NAMESPACES = [
    (workspace_ns, ("workspaces",)),
    (workspace_features_ns, ("workspaces",)),
    (workspace_tables_ns, ("workspace-tables",)),
    (llm_roles_ns, ("llm-roles",)),
    (llm_providers_ns, ("llm-providers",)),
    (workspace_llm_ns, tuple()),
]
