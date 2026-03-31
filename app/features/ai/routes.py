from .ai_api import ai_ns
from .chat_api import chat_ns
from .nlp_api import nlp_ns
from .nlp_review_api import nlp_review_ns
from .nlp_tier2_api import nlp_tier2_ns
from .prompt_feedback_api import prompt_feedback_ns

NAMESPACES = [
    (ai_ns, ("ai",)),
    (nlp_ns, ("nlp",)),
    (nlp_tier2_ns, ("nlp",)),
    (nlp_review_ns, ("nlp",)),
    (chat_ns, ("chat",)),
    (prompt_feedback_ns, ("prompt-feedback",)),
]
