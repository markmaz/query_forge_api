from .execution_api import executions_ns
from .export_api import exports_ns

NAMESPACES = [
    (executions_ns, ("executions",)),
    (exports_ns, ("exports",)),
]
