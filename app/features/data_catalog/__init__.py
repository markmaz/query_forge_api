from app.api_config import build_url, NAME, VERSION
from app.routes.dictionary_routes import dictionary_ns
from app.routes.domain_routes import qf_domains_ns
from app.routes.workspace_inventory_routes import wsinv_ns


def register(api):
    api.add_namespace(dictionary_ns, path=build_url("/", NAME, VERSION, "dictionary"))
    api.add_namespace(qf_domains_ns, path=build_url("/", NAME, VERSION, "domains"))
    api.add_namespace(wsinv_ns, path=build_url("/", NAME, VERSION, "workspace-inventory"))
