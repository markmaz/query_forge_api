from app.api_config import NAME, VERSION, build_url
from app.features.query_engine.query_forge_api import query_forge_ns
from app.features.query_engine.query_studio_api import query_studio_ns
from app.features.query_engine.query_studio_summary_api import query_studio_summary_ns
from app.features.query_engine.query_tree_api import qf_tree_ns


def register(api):
    api.add_namespace(query_forge_ns, path=build_url("/", NAME, VERSION, "query"))
    api.add_namespace(query_studio_ns, path=build_url("/", NAME, VERSION, "query-studio"))
    api.add_namespace(query_studio_summary_ns, path=build_url("/", NAME, VERSION, "query-studio"))
    api.add_namespace(qf_tree_ns, path=build_url("/", NAME, VERSION, "query-tree"))
