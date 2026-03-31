from app.api_config import NAME, VERSION, build_url
from app.routes.forge_insights import forge_insights_ns
from app.routes.forge_match_routes import forge_match_ns


def register(api):
    api.add_namespace(forge_match_ns, path=build_url("/", NAME, VERSION, "forge-match"))
    api.add_namespace(forge_insights_ns, path=build_url("/", NAME, VERSION, "forge-insights"))
