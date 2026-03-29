from app.api_config import build_url, NAME, VERSION
from app.routes.auth_routes import qf_auth_ns
from app.routes.otp_routes import otp_ns
from app.routes.public_sales_inquiry import public_ns


def register(api):
    api.add_namespace(qf_auth_ns, path=build_url("/", NAME, VERSION, "auth"))
    api.add_namespace(otp_ns, path=build_url("/", NAME, VERSION, "otp"))
    api.add_namespace(public_ns, path=build_url("/", NAME, VERSION, "public"))
