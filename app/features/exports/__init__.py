from .routes import executions_ns, exports_ns
from app.api_config import build_url, NAME, VERSION


def register(api):
    api.add_namespace(executions_ns, path=build_url("/", NAME, VERSION, "executions"))
    api.add_namespace(exports_ns, path=build_url("/", NAME, VERSION, "exports"))
