from __future__ import annotations

from app.features.flowforge.routes.common import (
    _actor_user_id,
    _int_query_arg,
    _service,
    _webhook_payload,
    _webhook_token,
    _workspace_id,
    flowforge_ns,
    models,
)

# Import endpoint modules for their Flask-RESTX route registration side effects.
from app.features.flowforge.routes import integrations as _integrations  # noqa: F401,E402
from app.features.flowforge.routes import human_tasks as _human_tasks  # noqa: F401,E402
from app.features.flowforge.routes import matching as _matching  # noqa: F401,E402
from app.features.flowforge.routes import reports as _reports  # noqa: F401,E402
from app.features.flowforge.routes import resources as _resources  # noqa: F401,E402
from app.features.flowforge.routes import runs as _runs  # noqa: F401,E402
from app.features.flowforge.routes import settings as _settings  # noqa: F401,E402
from app.features.flowforge.routes import webhooks as _webhooks  # noqa: F401,E402
from app.features.flowforge.routes import workflows as _workflows  # noqa: F401,E402


def register(api) -> None:
    from app.api_config import NAME, VERSION, build_url

    api.add_namespace(flowforge_ns, path=build_url("/", NAME, VERSION, "flowforge"))


__all__ = [
    "flowforge_ns",
    "models",
    "register",
    "_actor_user_id",
    "_int_query_arg",
    "_service",
    "_webhook_payload",
    "_webhook_token",
    "_workspace_id",
]
