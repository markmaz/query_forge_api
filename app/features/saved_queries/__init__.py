from .routes import qf_saved_query_ns, query_analysis_ns
from app.api_config import build_url, NAME, VERSION


def register(api):
    api.add_namespace(qf_saved_query_ns, path=build_url("/", NAME, VERSION, "saved-queries"))
    api.add_namespace(query_analysis_ns, path=build_url("/", NAME, VERSION, "queries"))
