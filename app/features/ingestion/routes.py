from .datasource_api import datasource_ns
from .ingestion_api import ingestion_ns

NAMESPACES = [
    (ingestion_ns, ("ingestion",)),
    (datasource_ns, ("datasources",)),
]
