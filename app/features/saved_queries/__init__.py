from app.api_config import build_url, NAME, VERSION
from app.routes.query_analysis_routes import query_analysis_ns
from app.routes.query_tree_routes import qf_saved_query_ns


def register(api):
    api.add_namespace(qf_saved_query_ns, path=build_url("/", NAME, VERSION, "saved-queries"))
    api.add_namespace(query_analysis_ns, path=build_url("/", NAME, VERSION, "queries"))
