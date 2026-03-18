from .routes import qf_auth_ns, otp_ns, public_ns
from app.api_config import build_url, NAME, VERSION


def register(api):
    api.add_namespace(qf_auth_ns, path=build_url("/", NAME, VERSION, "auth"))
    api.add_namespace(otp_ns, path=build_url("/", NAME, VERSION, "otp"))
    api.add_namespace(public_ns, path=build_url("/", NAME, VERSION, "public"))
