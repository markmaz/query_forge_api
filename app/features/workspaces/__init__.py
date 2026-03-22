from .routes import workspace_ns, workspace_tables_ns, workspace_llm_ns, llm_roles_ns, llm_providers_ns, workspace_features_ns
from app.api_config import build_url, NAME, VERSION


def register(api):
    api.add_namespace(workspace_ns, path=build_url("/", NAME, VERSION, "workspaces"))
    api.add_namespace(workspace_features_ns, path=build_url("/", NAME, VERSION, "workspaces"))
    api.add_namespace(workspace_tables_ns, path=build_url("/", NAME, VERSION, "workspace-tables"))
    api.add_namespace(llm_roles_ns, path=build_url("/", NAME, VERSION, "llm-roles"))
    api.add_namespace(llm_providers_ns, path=build_url("/", NAME, VERSION, "llm-providers"))
    api.add_namespace(workspace_llm_ns, path=build_url("/", NAME, VERSION))
