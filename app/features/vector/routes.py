from app.routes.domain_profile_embeddings import domain_profile_embeddings_ns
from app.routes.embeddings import embeddings_ns
from app.routes.vector_domains import vector_ns

NAMESPACES = [
    (vector_ns, ("vector",)),
    (embeddings_ns, ("embeddings",)),
    (domain_profile_embeddings_ns, ("domain-profiles",)),
]
