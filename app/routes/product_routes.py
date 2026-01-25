from flask import jsonify, request
from flask_restx import Namespace, Resource, reqparse

from app.decorators.security import token_required
from app.models.product import Product
from app.services.product_service import ProductService
from app.services.role_service import RoleService

product_ns = Namespace("products", description="A product available in Workboard")
product_parser = reqparse.RequestParser()
product_parser.add_argument('status', type=str, default='All', help='Filter by status', action='store', location='args')  # Single value
product_parser.add_argument('cursor', type=str, help='Cursor for pagination (user_id)', location='args')
product_parser.add_argument('limit', type=int, default=10, help='Number of records per page', location='args')
product_parser.add_argument('direction', type=str, default='forward', choices=['forward', 'backward'], help='Pagination direction', location='args')

@product_ns.route("/")
class ProductList(Resource):
    @token_required
    def get(self):
        args = product_parser.parse_args()
        service = ProductService()
    
        products, next_cursor, prev_cursor, total_count = service.get_products(
            status=args['status'],
            cursor=args['cursor'],
            limit=args['limit'],
            direction=args['direction']
        )
        return {
            'products': [product.model_dump(mode="json") for product in products],
            'next_cursor': next_cursor,
            'prev_cursor': prev_cursor,
            'total_count': total_count
        }, 200
    
    @token_required
    def post(self):
        data = request.get_json()
        product_name = data.get("product_name")
        product_group_id = data.get("product_group_id")
        role_ids = data.get("role_ids")

        service = ProductService()
        results = service.create_product(product_name, product_group_id, role_ids)

        return results

@product_ns.route("/counts")
class ProductCounts(Resource):
    def get(self):
        ps = ProductService()

        results = ps.get_counts()

        return results, 200

@product_ns.route("/<string:product_id>")
class ProductStandard(Resource):

    @token_required
    def get(self, product_id: str):
        service = ProductService()
        return service.get_product(product_id).model_dump(mode="json")
    
    def delete(self, product_id: str):
        service = ProductService()
        return service.delete(product_id)
    
    def put(self, product_id: str):
        service = ProductService()
        product = Product(**(request.get_json(force=True) or {}))
        new_product = service.update_product(product_id, product)

        return jsonify(new_product.model_dump(mode="json"))

@product_ns.route("/<string:product_id>/roles")
class ProductRoles(Resource):
    @token_required
    def get(self, product_id: str):
        pass

    @token_required
    def put(self, product_id: str):
        service = RoleService()

        data = request.get_json()
        return service.map_product_to_role(product_id=product_id, role_id=data.get("role_id"))

    
@product_ns.route("/<string:product_id>/roles/<string:role_id>")
class DeleteProductRoles(Resource):
    @token_required
    def delete(self, product_id: str, role_id: str):
        service = RoleService()

        return service.remove_role_from_product(product_id, role_id=role_id)

@product_ns.route("/sigma")
class SigmaProduct(Resource):
    @token_required
    def post(self):
        return {"status": "ok"}, 200

        
