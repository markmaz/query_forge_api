
import urllib.parse
from typing import Dict, Optional

from flask import request
from flask_restx import Namespace, Resource, fields, reqparse

from app.decorators.security import token_required
from app.services.user_service import UserService

parser = reqparse.RequestParser()
parser.add_argument('user_id', type=str, required=True, help='The user id', location='args')
parser.add_argument('workspace_id', type=str, required=True, help='The workspace id', location='args')

user_workspace_ns = Namespace("user-workspaces", description="Manage the user to workspace relationship")
mapping_model = user_workspace_ns.model('UserWorkspaceMapping', {
    'user_id': fields.String(required=True, description='The ID of the user'),
    'workspace_id': fields.String(required=True, description='The ID of the workspace'),
    'is_default': fields.Boolean(required=False, description='Is this is the default workspace for the user.')
})

connection_response = user_workspace_ns.model('ConnectionResponse', {
    'message': fields.String(description='Success or error message'),
})

@user_workspace_ns.route("")
@user_workspace_ns.doc()
class UserWorkspaceMap(Resource):
    @token_required
    @user_workspace_ns.doc(
        description=(
            "## User to Organization Mapping\n"
            "This endpoint allows clients to create a relationship between a user and an organization.\n\n"
            "**Required URL Parameters:**\n"
            "- `user_id`: The id of the given user.\n"
            "- `workspace_id`: The ID of the organization's Databricks workspace\n\n"
            "**Response Codes:**\n"
            "- `201`: Example created successfully.\n"
            "- `400`: Invalid input."
        )
    )
    @user_workspace_ns.expect(mapping_model)
    @user_workspace_ns.response(201, "Mapping created successfully", connection_response)
    @user_workspace_ns.response(400, "Invalid input")
    def post(self):
        """
        Maps a given user to the given organization
        """
        data = request.get_json(silent=True) or {}
        if not isinstance(data, dict):
            return {"error": "Invalid JSON body"}, 400
        user_id = data.get("user_id")
        workspace_id = data.get("workspace_id")
        is_default = False

        if not user_id or not workspace_id:
            return {"error": "user_id and workspace_id are required"}, 400

        if data.get("is_default"):
            is_default = data.get("is_default")
        
        user_service = UserService()
        results = user_service.map_user_organization(user_id, workspace_id, is_default)
        return results
    
    @token_required
    @user_workspace_ns.expect(parser)
    @user_workspace_ns.response(200, 'Mapping deleted successfully', connection_response)
    @user_workspace_ns.response(400, 'Missing required query parameter')
    def delete(self):
        """
        Deletes the given relationship between a user and a workspace
        """
        args: Dict[str, Optional[str]] = parser.parse_args()
        arg_user_id: Optional[str] = args.get('user_id')
        arg_workspace_id: Optional[str] = args.get('workspace_id')

        if not arg_user_id:
            return {"error": "Missing required query parameter 'user_id'"}, 400

        if not arg_workspace_id:
            return {"error": "Missing required query parameter 'workspace_id'"}, 400
        
        user_id: str = urllib.parse.quote(arg_user_id)
        workspace_id: str = urllib.parse.quote(arg_workspace_id)

        user_service = UserService()
        results = user_service.delete_user_workspace(user_id, workspace_id)
        return results
    
    @token_required
    @user_workspace_ns.expect(parser)
    @user_workspace_ns.response(200, 'Connection retrieved successfully', connection_response)
    @user_workspace_ns.response(400, 'Missing required query parameter')
    def put(self):
        """
        Updates the given relationship between a user and a workspace
        """
        data = request.get_json(silent=True) or {}
        if not isinstance(data, dict):
            return {"error": "Invalid JSON body"}, 400
        user_id = data.get("user_id")
        workspace_id = data.get("workspace_id")
        is_default = False

        if not user_id or not workspace_id:
            return {"error": "user_id and workspace_id are required"}, 400

        if data.get("is_default"):
            is_default = data.get("is_default")
        
        user_service = UserService()
        results = user_service.set_workspace_default(user_id, workspace_id, is_default)
        return results
