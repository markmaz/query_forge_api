from app.routes.datasource_routes import datasource_ns
from app.routes.ingestion_routes import ingestion_ns

NAMESPACES = [
    (ingestion_ns, ("ingestion",)),
    (datasource_ns, ("datasources",)),
]
