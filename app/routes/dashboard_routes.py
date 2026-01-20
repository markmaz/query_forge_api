import logging
from typing import Dict, Optional

from flask_restx import Namespace, Resource, fields, reqparse

from app.config import SIGMA_TAGS, SIGMA_WORKSPACE
from app.decorators.security import token_required
from app.services.dashboard_service import DashboardService

logger = logging.getLogger(__name__)
dashboard_ns = Namespace("dashboards", description="Dashboards")

parser = reqparse.RequestParser()
parser.add_argument('name', type=str, required=False, help='The name of the tag', location='args')

dashboard_model = dashboard_ns.model("Dashboard",    {
        "workbookId": fields.String(readOnly=True),
        "workbookUrlId": fields.String(readOnly=True),
        "createdBy": fields.String(readOnly=True),
        "updatedBy": fields.String(readOnly=True),
        "createdAt": fields.String(readOnly=True),
        "updatedAt": fields.String(readOnly=True),
        "name": fields.String(readOnly=True),
        "url": fields.String(readOnly=True),
        "path": fields.String(readOnly=True),
        "latestVersion": fields.Integer(readOnly=True),
      
        "ownerId": fields.String(readOnly=True)
    })

workspace_model = dashboard_ns.model("Workspace", {
            "workspaceId": fields.String(readOnly=True),
            "name": fields.String(readOnly=True),
            "createdBy": fields.String(readOnly=True),
            "updatedBy": fields.String(readOnly=True),
            "createdAt": fields.String(readOnly=True),
            "updatedAt": fields.String(readOnly=True)
        })

workspace_entries = dashboard_ns.model("WorkspaceList", 
        {
            "entries": fields.List(fields.Nested(workspace_model))
                                           
        })

workbook_model = dashboard_ns.model("Workbook", {
    "entries": fields.List(fields.Nested(dashboard_model))
})

@dashboard_ns.route("/")
@dashboard_ns.response(code=200, description="The list of Dashboards specific to the Provider UI")
class DashboardList(Resource):
    @dashboard_ns.marshal_list_with(dashboard_model)
    @token_required
    def get(self):
        """
        Gets the list of available workbooks (dashboards) from Sigma for the Navigator App
        """
        sigma = DashboardService()
        logger.info(f"Getting dashboards for: {SIGMA_WORKSPACE}")
        return sigma.list_workbooks_in_workspace(SIGMA_WORKSPACE, SIGMA_TAGS), 200
    
    def options(self):
        return {}, 200

@dashboard_ns.route("/workspaces")
@dashboard_ns.response(200, "The list of Sigma Workspaces", workspace_entries)
class DashboardWorkspaces(Resource):
    @token_required
    def get(self):
        """
        Gets all the available Workspaces in Sigma
        """
        sigma = DashboardService()
        return sigma.get_workspaces()

@dashboard_ns.route("/workbooks")
@dashboard_ns.response(200, "The list of Sigma Workbooks", workbook_model)
class DashboardWorkbooks(Resource):
    @token_required
    def get(self):
        """
        Gets all the available workbooks (dashboards) in Sigma
        """
        sigma = DashboardService()
        return sigma.get_workbooks()

@dashboard_ns.route("/<string:workbook_id>/embed")
@dashboard_ns.response(200, "Embed found")
class DashboardEmbed(Resource):
    @token_required
    def get(self, workbook_id):
        """
        This call will get the existing embed ID for a given workbook (dashboard) or create it.
        """
        sigma = DashboardService()
        print(workbook_id)
        return sigma.get_embed_for_dashboard(workbook_id=workbook_id)
    
@dashboard_ns.route("/tags")
@dashboard_ns.expect(parser)
@dashboard_ns.response(200, "Tags found")
class DashboardTags(Resource):
    @token_required
    def get(self):
        """
        Get all the Sigma Tags
        """
        args: Dict[str, Optional[str]] = parser.parse_args()
        tag_name: Optional[str] = args.get('name')
        
        logger.info(f"Arguments: {args}")
        sigma = DashboardService()

        if tag_name:
           return sigma.get_tags_by_name(tag_name)
        else:
            return sigma.get_tags()
        
@dashboard_ns.route("/workbooks/<string:workbook_id>/tags")
@dashboard_ns.expect(parser)
@dashboard_ns.response(200, "Tags found")
class DashboardTag(Resource):
    @token_required
    def get(self, workbook_id: str):
        """
        Gets thes tag for the given workbook
        """
        sigma = DashboardService()
        return sigma.verify_tags(workbook_id, SIGMA_TAGS)
        