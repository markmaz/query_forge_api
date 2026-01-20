from flask import request
from flask_restx import Namespace, Resource, fields

from app.decorators.security import token_required
from app.services.role_service import RoleService

role_ns = Namespace("roles", description="Role management")

role_model = role_ns.model("role", {
    "role_id": fields.String(required=True, description="THe unique identifier of the role"),
    "name": fields.String(require=True, description="The name of the role")

})

roles = role_ns.model("role_list", {"roles": fields.List(fields.Nested(role_model))})


@role_ns.route("")
@role_ns.response(200, "The list of roles", roles)
class RoleList(Resource):
    @role_ns.expect()
    @token_required
    def get(self):
        """
        Gets a list of all available roles
        """
        roleService = RoleService()
        return roleService.get_roles()
    
    @token_required
    def post(self):
        data = request.json
        roleService = RoleService()
        return roleService.add_role(data["role_name"]), 201
    

@role_ns.route("/<string:role_id>")
class RoleDetails(Resource):
    @token_required
    def delete(self, role_id):
        roleService = RoleService()
        return roleService.delete_role(role_id)

    @token_required
    def get(self, role_id):
        roleService = RoleService()
        return roleService.get_role(role_id)
