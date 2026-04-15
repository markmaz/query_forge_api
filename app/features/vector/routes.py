from app.api_config import NAME, VERSION, build_url
from app.routes.embeddings import embeddings_ns

from .domain_profile_embeddings_api import domain_profile_embeddings_ns
from .vector_api import vector_ns


def register(api):
    api.add_namespace(vector_ns, path=build_url("/", NAME, VERSION, "vector"))
    api.add_namespace(embeddings_ns, path=build_url("/", NAME, VERSION, "embeddings"))
    api.add_namespace(domain_profile_embeddings_ns, path=build_url("/", NAME, VERSION, "domain-profiles"))
