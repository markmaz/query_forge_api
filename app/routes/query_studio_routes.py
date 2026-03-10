from __future__ import annotations

import logging
from typing import Any, Callable, Tuple

from flask_restx import Namespace

from app.decorators.security import token_required
from app.exceptions.forge_error import ForgeError
from app.routes.forge_resource import ForgeResource
from app.routes.request_helpers import extract_workspace_id, require_user_id
from app.services.query_studio import QueryStudioDomainExplorerService

logger = logging.getLogger(__name__)

query_studio_ns = Namespace("query-studio", description="Query Studio metadata endpoints")


def _run(handler: Callable[[], Tuple[Any, int]], *, log_message: str, client_error: str):
    try:
        return handler()
    except ForgeError as error:
        return {"error": str(error)}, getattr(error, "status_code", 400) or 400
    except Exception:
        logger.exception(log_message)
        return {"error": client_error}, 500


@query_studio_ns.route("/domains")
class QueryStudioDomains(ForgeResource):
    @token_required
    def get(self):
        def handler() -> Tuple[Any, int]:
            rows = QueryStudioDomainExplorerService().list_domains(
                workspace_id=extract_workspace_id(),
                user_id=require_user_id(),
            )
            return rows, 200

        return _run(handler, log_message="Query Studio domains fetch failed", client_error="Domains fetch failed")


@query_studio_ns.route("/domains/<int:domain_id>/explorer")
class QueryStudioDomainExplorer(ForgeResource):
    @token_required
    def get(self, domain_id: int):
        def handler() -> Tuple[Any, int]:
            payload = QueryStudioDomainExplorerService().get_domain_explorer(
                workspace_id=extract_workspace_id(),
                user_id=require_user_id(),
                domain_id=int(domain_id),
            )
            return payload, 200

        return _run(
            handler,
            log_message=f"Query Studio domain explorer fetch failed domain_id={domain_id}",
            client_error="Domain explorer fetch failed",
        )
