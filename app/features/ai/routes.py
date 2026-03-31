from app.api_config import NAME, VERSION, build_url
from app.routes.ai import ai_ns
from app.routes.chat_minimal import chat_ns
from app.routes.nlp_review import nlp_review_ns
from app.routes.nlp_routes import nlp_ns
from app.routes.nlp_tier2 import nlp_tier2_ns
from app.routes.prompt_feedback import prompt_feedback_ns


def register(api):
    api.add_namespace(ai_ns, path=build_url("/", NAME, VERSION, "ai"))
    api.add_namespace(nlp_ns, path=build_url("/", NAME, VERSION, "nlp"))
    api.add_namespace(nlp_tier2_ns, path=build_url("/", NAME, VERSION, "nlp"))
    api.add_namespace(nlp_review_ns, path=build_url("/", NAME, VERSION, "nlp"))
    api.add_namespace(chat_ns, path=build_url("/", NAME, VERSION, "chat"))
    api.add_namespace(prompt_feedback_ns, path=build_url("/", NAME, VERSION, "prompt-feedback"))
