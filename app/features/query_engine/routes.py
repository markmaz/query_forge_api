from .query_api import query_forge_ns
from .query_studio_api import query_studio_ns
from .query_studio_summary_api import query_studio_summary_ns

NAMESPACES = [
    (query_forge_ns, ("query",)),
    (query_studio_ns, ("query-studio",)),
    (query_studio_summary_ns, ("query-studio",)),
]
