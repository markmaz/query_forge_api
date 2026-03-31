from app.api_config import NAME, VERSION, build_url
from app.features.planner import planner_domain_api as _planner_domain  # noqa: F401
from app.features.planner import planner_llm_api as _planner_llm  # noqa: F401
from app.features.planner.planner_extract_api import planner_ns


def register(api):
    api.add_namespace(planner_ns, path=build_url("/", NAME, VERSION, "planner"))
