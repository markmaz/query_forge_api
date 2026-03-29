from app.api_config import build_url, NAME, VERSION
from app.routes.execution_routes import executions_ns
from app.routes.export_routes import exports_ns


def register(api):
    api.add_namespace(executions_ns, path=build_url("/", NAME, VERSION, "executions"))
    api.add_namespace(exports_ns, path=build_url("/", NAME, VERSION, "exports"))
