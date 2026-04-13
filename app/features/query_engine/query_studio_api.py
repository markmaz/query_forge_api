from __future__ import annotations

import logging
from typing import Any, Callable, Tuple

from flask_restx import Namespace, Resource

from app.decorators.rbac import require_access
from app.decorators.security import token_required
from app.routes.request_helpers import extract_workspace_id, require_user_id
from app.services.query_studio import QueryStudioDomainExplorerService

logger = logging.getLogger(__name__)

query_studio_ns = Namespace("query-studio", description="Query Studio metadata endpoints")


def _run(handler: Callable[[], Tuple[Any, int]]):
    return handler()


@query_studio_ns.route("/domains")
class QueryStudioDomains(Resource):
    @token_required
    @require_access("query_studio")
    def get(self):
        def handler() -> Tuple[Any, int]:
            rows = QueryStudioDomainExplorerService().list_domains(
                workspace_id=extract_workspace_id(),
                user_id=require_user_id(),
            )
            return rows, 200

        return _run(handler)


@query_studio_ns.route("/domains/<int:domain_id>/explorer")
class QueryStudioDomainExplorer(Resource):
    @token_required
    @require_access("query_studio")
    def get(self, domain_id: int):
        def handler() -> Tuple[Any, int]:
            payload = QueryStudioDomainExplorerService().get_domain_explorer(
                workspace_id=extract_workspace_id(),
                user_id=require_user_id(),
                domain_id=int(domain_id),
            )
            return payload, 200

        return _run(handler)
