from .routes import ingestion_ns, datasource_ns
from app.api_config import build_url, NAME, VERSION


def register(api):
    api.add_namespace(ingestion_ns, path=build_url("/", NAME, VERSION, "ingestion"))
    api.add_namespace(datasource_ns, path=build_url("/", NAME, VERSION, "datasources"))
