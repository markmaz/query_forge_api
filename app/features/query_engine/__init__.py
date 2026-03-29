from app.api_config import build_url, NAME, VERSION
from app.routes.query_forge_routes import query_forge_ns
from app.routes.query_studio_summary_routes import query_studio_summary_ns
from app.routes.query_studio_routes import query_studio_ns
from app.routes.query_tree_routes import qf_tree_ns


def register(api):
    api.add_namespace(query_forge_ns, path=build_url("/", NAME, VERSION, "query"))
    api.add_namespace(query_studio_ns, path=build_url("/", NAME, VERSION, "query-studio"))
    api.add_namespace(query_studio_summary_ns, path=build_url("/", NAME, VERSION, "query-studio"))
    api.add_namespace(qf_tree_ns, path=build_url("/", NAME, VERSION, "query-tree"))
