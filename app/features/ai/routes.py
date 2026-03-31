from app.routes.ai import ai_ns
from app.routes.chat_minimal import chat_ns
from app.routes.nlp_review import nlp_review_ns
from app.routes.nlp_routes import nlp_ns
from app.routes.nlp_tier2 import nlp_tier2_ns
from app.routes.prompt_feedback import prompt_feedback_ns

NAMESPACES = [
    (ai_ns, ("ai",)),
    (nlp_ns, ("nlp",)),
    (nlp_tier2_ns, ("nlp",)),
    (nlp_review_ns, ("nlp",)),
    (chat_ns, ("chat",)),
    (prompt_feedback_ns, ("prompt-feedback",)),
]
