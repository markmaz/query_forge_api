from app.routes.auth_routes import qf_auth_ns
from app.routes.otp_routes import otp_ns
from app.routes.public_sales_inquiry import public_ns

NAMESPACES = [
    (qf_auth_ns, ("auth",)),
    (otp_ns, ("otp",)),
    (public_ns, ("public",)),
]
