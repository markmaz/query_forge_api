from .destination_api import destinations_ns
from .skills_api import skills_ns

NAMESPACES = [
    (skills_ns, ("skills",)),
    (destinations_ns, ("workspaces", "<workspace_id>", "destinations")),
]
