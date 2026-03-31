from app.routes.destination_routes import destinations_ns
from app.routes.skills_routes import skills_ns

NAMESPACES = [
    (skills_ns, ("skills",)),
    (destinations_ns, ("workspaces", "<workspace_id>", "destinations")),
]
