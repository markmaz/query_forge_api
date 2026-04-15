from app.api_config import NAME, VERSION, build_url
from app.features.workspaces.workspace_api import workspace_ns
from app.features.workspaces.workspace_feature_api import workspace_features_ns
from app.features.workspaces.workspace_llm_api import llm_providers_ns, llm_roles_ns, workspace_llm_ns
from app.features.workspaces.workspace_table_api import workspace_tables_ns


def register(api):
    api.add_namespace(workspace_ns, path=build_url("/", NAME, VERSION, "workspaces"))
    api.add_namespace(workspace_features_ns, path=build_url("/", NAME, VERSION, "workspaces"))
    api.add_namespace(workspace_tables_ns, path=build_url("/", NAME, VERSION, "workspace-tables"))
    api.add_namespace(llm_roles_ns, path=build_url("/", NAME, VERSION, "llm-roles"))
    api.add_namespace(llm_providers_ns, path=build_url("/", NAME, VERSION, "llm-providers"))
    api.add_namespace(workspace_llm_ns, path=build_url("/", NAME, VERSION))
