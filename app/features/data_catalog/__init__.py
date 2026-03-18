from .routes import dictionary_ns, qf_domains_ns, wsinv_ns
from app.api_config import build_url, NAME, VERSION


def register(api):
    api.add_namespace(dictionary_ns, path=build_url("/", NAME, VERSION, "dictionary"))
    api.add_namespace(qf_domains_ns, path=build_url("/", NAME, VERSION, "domains"))
    api.add_namespace(wsinv_ns, path=build_url("/", NAME, VERSION, "workspace-inventory"))
