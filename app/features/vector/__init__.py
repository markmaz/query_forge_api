from .routes import vector_ns, embeddings_ns, domain_profile_embeddings_ns
from app.api_config import build_url, NAME, VERSION


def register(api):
    api.add_namespace(vector_ns, path=build_url("/", NAME, VERSION, "vector"))
    api.add_namespace(embeddings_ns, path=build_url("/", NAME, VERSION, "embeddings"))
    api.add_namespace(domain_profile_embeddings_ns, path=build_url("/", NAME, VERSION, "domain-profiles"))
