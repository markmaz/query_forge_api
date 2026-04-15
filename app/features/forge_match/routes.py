from app.api_config import NAME, VERSION, build_url

from .forge_insights_api import forge_insights_ns
from .forge_match_api import forge_match_ns


def register(api):
    api.add_namespace(forge_match_ns, path=build_url("/", NAME, VERSION, "forge-match"))
    api.add_namespace(forge_insights_ns, path=build_url("/", NAME, VERSION, "forge-insights"))
