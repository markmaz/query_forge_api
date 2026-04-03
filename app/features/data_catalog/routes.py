from app.api_config import NAME, VERSION, build_url
from app.routes.dictionary_routes import dictionary_ns
from app.features.data_catalog.workspace_inventory_api import wsinv_ns


def register(api):
    api.add_namespace(dictionary_ns, path=build_url("/", NAME, VERSION, "dictionary"))
    api.add_namespace(wsinv_ns, path=build_url("/", NAME, VERSION, "workspace-inventory"))
