from .routes import planner_ns
from app.api_config import build_url, NAME, VERSION


def register(api):
    api.add_namespace(planner_ns, path=build_url("/", NAME, VERSION, "planner"))
