from app.api_config import NAME, VERSION, build_url

from .ai_api import ai_ns
from .chat_api import chat_ns
from .nlp_api import nlp_ns
from .nlp_review_api import nlp_review_ns
from .nlp_tier2_api import nlp_tier2_ns
from .prompt_feedback_api import prompt_feedback_ns


def register(api):
    api.add_namespace(ai_ns, path=build_url("/", NAME, VERSION, "ai"))
    api.add_namespace(nlp_ns, path=build_url("/", NAME, VERSION, "nlp"))
    api.add_namespace(nlp_tier2_ns, path=build_url("/", NAME, VERSION, "nlp"))
    api.add_namespace(nlp_review_ns, path=build_url("/", NAME, VERSION, "nlp"))
    api.add_namespace(chat_ns, path=build_url("/", NAME, VERSION, "chat"))
    api.add_namespace(prompt_feedback_ns, path=build_url("/", NAME, VERSION, "prompt-feedback"))
