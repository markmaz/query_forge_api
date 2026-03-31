from .domain_profile_embeddings_api import domain_profile_embeddings_ns
from .embeddings_api import embeddings_ns
from .vector_api import vector_ns

NAMESPACES = [
    (vector_ns, ("vector",)),
    (embeddings_ns, ("embeddings",)),
    (domain_profile_embeddings_ns, ("domain-profiles",)),
]
