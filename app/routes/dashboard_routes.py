from flask_restx import Namespace, Resource, fields, reqparse

from app.decorators.security import token_required

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
    @token_required
    def get(self):
        """
        Dashboard endpoints are temporarily disabled.
        """
        return {"status": "ok"}, 200
    
    def options(self):
        return {}, 200

@dashboard_ns.route("/workspaces")
@dashboard_ns.response(200, "The list of Sigma Workspaces", workspace_entries)
class DashboardWorkspaces(Resource):
    @token_required
    def get(self):
        """
        Dashboard endpoints are temporarily disabled.
        """
        return {"status": "ok"}, 200

@dashboard_ns.route("/workbooks")
@dashboard_ns.response(200, "The list of Sigma Workbooks", workbook_model)
class DashboardWorkbooks(Resource):
    @token_required
    def get(self):
        """
        Dashboard endpoints are temporarily disabled.
        """
        return {"status": "ok"}, 200

@dashboard_ns.route("/<string:workbook_id>/embed")
@dashboard_ns.response(200, "Embed found")
class DashboardEmbed(Resource):
    @token_required
    def get(self, workbook_id):
        """
        Dashboard endpoints are temporarily disabled.
        """
        return {"status": "ok"}, 200
    
@dashboard_ns.route("/tags")
@dashboard_ns.expect(parser)
@dashboard_ns.response(200, "Tags found")
class DashboardTags(Resource):
    @token_required
    def get(self):
        """
        Dashboard endpoints are temporarily disabled.
        """
        return {"status": "ok"}, 200
        
@dashboard_ns.route("/workbooks/<string:workbook_id>/tags")
@dashboard_ns.expect(parser)
@dashboard_ns.response(200, "Tags found")
class DashboardTag(Resource):
    @token_required
    def get(self, workbook_id: str):
        """
        Dashboard endpoints are temporarily disabled.
        """
        return {"status": "ok"}, 200
        
