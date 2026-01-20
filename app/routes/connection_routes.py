import urllib.parse
from typing import Any, Dict, Optional, Tuple

from flask_restx import Namespace, Resource, fields, reqparse

from app.decorators.security import token_required
from app.services.connection_service import ConnectionService

# Namespace
connection_ns = Namespace("connections", description="Operations related to Sigma connections")

# Response model for documentation
connection_response = connection_ns.model('ConnectionResponse', {
    'message': fields.String(description='Success or error message'),
})

# Query parser for ?org= parameter
org_parser = reqparse.RequestParser()
org_parser.add_argument('org', type=str, required=False, help='The organization name', location='args')
org_parser.add_argument('host', type=str, required=False, help='The URL of the workspace', location='args')


@connection_ns.route("/")
class ConnectionList(Resource):
    @connection_ns.response(200, "List of all Sigma connections")
    @token_required
    def get(self) -> Tuple[Any, int]:
        """
        Retrieve a list of all defined connections from Sigma.

        Returns:
            Tuple[List[Dict[str, Any]], int]: A list of connection dictionaries and HTTP status code.
        """
        sigma = ConnectionService()
        return sigma.get_connections(), 200


@connection_ns.route("")
class Connection(Resource):
    @connection_ns.expect(org_parser)
    @connection_ns.response(200, 'Connection retrieved successfully', connection_response)
    @connection_ns.response(400, 'Missing required query parameter')
    @token_required
    def get(self) -> Tuple[Dict[str, Any], int]:
        """
        Retrieve a specific connection by organization.

        You must pass either the `org` or `host` query parameter in the URL, e.g., `/connections?org=arlo`.

        Returns:
            Tuple[Dict[str, Any], int]: Connection details and HTTP status code.
        """
        args: Dict[str, Optional[str]] = org_parser.parse_args()
        org: Optional[str] = args.get('org')
        host: Optional[str] = args.get('host')

        sigma = ConnectionService()

        if org:
            organization: str = urllib.parse.quote(org)            
            return sigma.get_connection_by_org(organization=organization), 200
        
        if host:
            host_url: str = urllib.parse.quote(host)
            return sigma.get_connection_by_host(host_url), 200
        

        return {"error": "Missing required query parameters 'org' or 'host"}, 400




@connection_ns.route("/<string:connection_id>")
@connection_ns.param('connection_id', 'The ID of the connection to retrieve')
class ConnectionByID(Resource):
    @connection_ns.response(200, 'Connection retrieved successfully', connection_response)
    @connection_ns.response(404, 'Connection not found')
    @token_required
    def get(self, connection_id: str) -> Tuple[Dict[str, Any], int]:
        """
        Retrieve a specific connection by its ID.

        Args:
            connection_id (str): The unique ID of the connection.

        Returns:
            Tuple[Dict[str, Any], int]: Connection details and HTTP status code.
        """
        sigma = ConnectionService()
        return sigma.get_connection_by_id(connection_id=connection_id), 200
