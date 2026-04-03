from app.api_config import NAME, VERSION, build_url
from app.features.domains.common import qf_domains_ns
from app.features.domains import domain_access_api  # noqa: F401
from app.features.domains import domain_admin_api  # noqa: F401
from app.features.domains import domain_builder_api  # noqa: F401
from app.features.domains import domain_planner_api  # noqa: F401
from app.features.domains import domain_profile_api  # noqa: F401
from app.features.domains import domain_topology_api  # noqa: F401


def register(api):
    api.add_namespace(qf_domains_ns, path=build_url("/", NAME, VERSION, "domains"))
