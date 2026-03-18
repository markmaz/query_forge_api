from .routes import ai_ns, nlp_ns, nlp_tier2_ns, nlp_review_ns, chat_ns, prompt_feedback_ns
from app.api_config import build_url, NAME, VERSION


def register(api):
    api.add_namespace(ai_ns, path=build_url("/", NAME, VERSION, "ai"))
    api.add_namespace(nlp_ns, path=build_url("/", NAME, VERSION, "nlp"))
    api.add_namespace(nlp_tier2_ns, path=build_url("/", NAME, VERSION, "nlp"))
    api.add_namespace(nlp_review_ns, path=build_url("/", NAME, VERSION, "nlp"))
    api.add_namespace(chat_ns, path=build_url("/", NAME, VERSION, "chat"))
    api.add_namespace(prompt_feedback_ns, path=build_url("/", NAME, VERSION, "prompt-feedback"))
