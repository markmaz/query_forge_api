from flask import request
from flask_restx import Namespace, Resource, reqparse

from app.decorators.security import token_required
from app.services.product_groups_service import ProductGroupService

product_group_ns = Namespace("product-groups", "A collection of products")
product_group_parser = reqparse.RequestParser()
product_group_parser.add_argument('status', type=str, default='All', help='Filter by status', action='store', location='args')  # Single value
product_group_parser.add_argument('cursor', type=str, help='Cursor for pagination (user_id)', location='args')
product_group_parser.add_argument('limit', type=int, default=10, help='Number of records per page', location='args')
product_group_parser.add_argument('direction', type=str, default='forward', choices=['forward', 'backward'], help='Pagination direction', location='args')

@product_group_ns.route("/")
class ProductGroupList(Resource):
    token_required
    def get(self):
        args = product_group_parser.parse_args()
        service = ProductGroupService()
    
        product_groups = service.get_product_groups(status=args['status'])
        return [product_group.model_dump(mode="json") for product_group in product_groups]
    
    token_required
    def post(self):
        service = ProductGroupService()
        data = request.get_json()
        group_name = data.get("product_group_name")
        return service.create_product_group(group_name).model_dump(mode="json")

@product_group_ns.route("/<string:product_group_id>")
class ProductGroupStandard(Resource):
    @token_required
    def get(self, product_group_id: str):
        service = ProductGroupService()
        product_group = service.get_product_group(product_group_id)

        return product_group.model_dump(mode="json")
    
    @token_required
    def delete(self, product_group_id: str):
        service = ProductGroupService()
        return service.delete_product_group(product_group_id)

@product_group_ns.route("/<string:product_group_id>/products/<string:product_id>")
class ProductGroupProductMap(Resource):
    def put(self, product_group_id: str, product_id:str):
        service = ProductGroupService()

        return service.add_product_to_group(product_id, product_group_id).model_dump(mode="json")

@product_group_ns.route("/<string:product_group_id>/products/<string:product_id>")
class ProductGroupRemoveProduct(Resource):
    def delete(self, product_group_id: str, product_id: str):
        service = ProductGroupService()

        return service.remove_product_from_group(product_id, product_group_id).model_dump(mode="json")