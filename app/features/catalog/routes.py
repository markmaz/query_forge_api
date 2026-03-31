from .catalog_api import catalog_ns
from .value_override_api import value_override_ns

NAMESPACES = [
    (catalog_ns, ("catalog",)),
    (value_override_ns, ("value_overrides",)),
]
