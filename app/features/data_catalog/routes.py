from app.routes.dictionary_routes import dictionary_ns
from app.routes.domain_routes import qf_domains_ns
from app.routes.workspace_inventory_routes import wsinv_ns

NAMESPACES = [
    (dictionary_ns, ("dictionary",)),
    (qf_domains_ns, ("domains",)),
    (wsinv_ns, ("workspace-inventory",)),
]
