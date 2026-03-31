from .forge_insights_api import forge_insights_ns
from .forge_match_api import forge_match_ns

NAMESPACES = [
    (forge_match_ns, ("forge-match",)),
    (forge_insights_ns, ("forge-insights",)),
]
