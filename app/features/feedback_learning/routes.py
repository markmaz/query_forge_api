from app.api_config import NAME, VERSION, build_url

from . import candidate_api, override_api  # noqa: F401
from .analysis_api import feedback_learning_ns


def register(api):
    api.add_namespace(feedback_learning_ns, path=build_url("/", NAME, VERSION, "feedback-learning"))
