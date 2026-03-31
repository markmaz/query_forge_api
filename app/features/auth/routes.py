from app.api_config import NAME, VERSION, build_url
from app.features.auth.auth_api import qf_auth_ns
from app.features.auth.otp_api import otp_ns
from app.features.auth.public_api import public_ns


def register(api):
    api.add_namespace(qf_auth_ns, path=build_url("/", NAME, VERSION, "auth"))
    api.add_namespace(otp_ns, path=build_url("/", NAME, VERSION, "otp"))
    api.add_namespace(public_ns, path=build_url("/", NAME, VERSION, "public"))
