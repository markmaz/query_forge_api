from .auth_api import qf_auth_ns
from .otp_api import otp_ns
from .public_api import public_ns

NAMESPACES = [
    (qf_auth_ns, ("auth",)),
    (otp_ns, ("otp",)),
    (public_ns, ("public",)),
]
