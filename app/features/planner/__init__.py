from app.api_config import build_url, NAME, VERSION
from app.routes import planner_domain as _planner_domain  # noqa: F401
from app.routes import planner_llm as _planner_llm  # noqa: F401
from app.routes.planner_extract import planner_ns


def register(api):
    api.add_namespace(planner_ns, path=build_url("/", NAME, VERSION, "planner"))
