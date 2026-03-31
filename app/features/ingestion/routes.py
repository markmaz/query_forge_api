from app.api_config import NAME, VERSION, build_url
from app.routes.datasource_routes import datasource_ns
from app.routes.ingestion_routes import ingestion_ns


def register(api):
    api.add_namespace(ingestion_ns, path=build_url("/", NAME, VERSION, "ingestion"))
    api.add_namespace(datasource_ns, path=build_url("/", NAME, VERSION, "datasources"))
