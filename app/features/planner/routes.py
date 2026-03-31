from . import planner_domain_api as _planner_domain_api  # noqa: F401
from . import planner_llm_api as _planner_llm_api  # noqa: F401
from .planner_extract_api import planner_ns

NAMESPACES = [
    (planner_ns, ("planner",)),
]
