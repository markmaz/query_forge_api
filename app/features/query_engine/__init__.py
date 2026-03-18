from .routes import query_forge_ns, query_studio_ns, qf_tree_ns
from app.api_config import build_url, NAME, VERSION


def register(api):
    api.add_namespace(query_forge_ns, path=build_url("/", NAME, VERSION, "query"))
    api.add_namespace(query_studio_ns, path=build_url("/", NAME, VERSION, "query-studio"))
    api.add_namespace(qf_tree_ns, path=build_url("/", NAME, VERSION, "query-tree"))
