from __future__ import annotations

from typing import Any
from urllib.parse import quote

from flask_restx import Namespace, fields, reqparse
from app.routes.forge_resource import ForgeResource

from app.decorators.security import token_required
from app.services.connection_service import ConnectionService

connection_ns = Namespace("connections", description="Operations related to Sigma connections")

connection_response = connection_ns.model(
    "ConnectionResponse",
    {"message": fields.String(description="Success or error message")},
)

_query_parser = reqparse.RequestParser()
_query_parser.add_argument("org", type=str, required=False, help="Organization name", location="args")
_query_parser.add_argument("host", type=str, required=False, help="Workspace host URL", location="args")


def _service() -> ConnectionService:
    return ConnectionService()


@connection_ns.route("/")
class ConnectionList(ForgeResource):
    @connection_ns.response(200, "List of all Sigma connections")
    @token_required
    def get(self) -> tuple[list[dict[str, Any]], int]:
        return _service().get_connections(), 200


@connection_ns.route("")
class Connection(ForgeResource):
    @connection_ns.expect(_query_parser)
    @connection_ns.response(200, "Connection retrieved successfully", connection_response)
    @connection_ns.response(400, "Missing required query parameter")
    @token_required
    def get(self) -> tuple[Any, int]:
        args = _query_parser.parse_args()
        org = args.get("org")
        host = args.get("host")
        svc = _service()

        if org:
            return svc.get_connection_by_org(organization=quote(org)), 200
        if host:
            return svc.get_connection_by_host(quote(host)), 200
        return {"error": "Missing required query parameters 'org' or 'host'"}, 400


@connection_ns.route("/<string:connection_id>")
@connection_ns.param("connection_id", "The ID of the connection to retrieve")
class ConnectionByID(ForgeResource):
    @connection_ns.response(200, "Connection retrieved successfully", connection_response)
    @connection_ns.response(404, "Connection not found")
    @token_required
    def get(self, connection_id: str) -> tuple[dict[str, Any], int]:
        return _service().get_connection_by_id(connection_id=connection_id), 200
