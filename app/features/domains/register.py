from app.api_config import NAME, VERSION, build_url

from app.features.domains import domain_access_api as _domain_access_api  # noqa: F401
from app.features.domains import domain_admin_api as _domain_admin_api  # noqa: F401
from app.features.domains import domain_builder_api as _domain_builder_api  # noqa: F401
from app.features.domains import domain_planner_api as _domain_planner_api  # noqa: F401
from app.features.domains import domain_profile_api as _domain_profile_api  # noqa: F401
from app.features.domains import domain_topology_api as _domain_topology_api  # noqa: F401
from app.features.domains.common import qf_domains_ns


def register(api):
    api.add_namespace(qf_domains_ns, path=build_url("/", NAME, VERSION, "domains"))
