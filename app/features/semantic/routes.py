from app.api_config import NAME, VERSION, build_url
from app.routes.semantic_concepts import (
    semantic_concept_aliases_ns,
    semantic_concept_column_maps_ns,
    semantic_concepts_ns,
    semantic_value_aliases_ns,
)
from app.routes.semantic_registry import semantic_registry_ns
from app.routes.semantic_relationships import semantic_relationships_ns
from app.routes.semantic_routes import semantic_ns
from app.routes.semantic_suggestions import semantic_suggestions_ns


def register(api):
    api.add_namespace(semantic_concepts_ns, path=build_url("/", NAME, VERSION, "semantic", "concepts"))
    api.add_namespace(semantic_concept_aliases_ns, path=build_url("/", NAME, VERSION, "semantic", "concept-aliases"))
    api.add_namespace(semantic_value_aliases_ns, path=build_url("/", NAME, VERSION, "semantic", "value-aliases"))
    api.add_namespace(semantic_concept_column_maps_ns, path=build_url("/", NAME, VERSION, "semantic", "concept-column-maps"))
    api.add_namespace(semantic_registry_ns, path=build_url("/", NAME, VERSION, "semantic", "registry"))
    api.add_namespace(semantic_relationships_ns, path=build_url("/", NAME, VERSION, "semantic", "relationships"))
    api.add_namespace(semantic_suggestions_ns, path=build_url("/", NAME, VERSION, "semantic", "suggestions"))
    api.add_namespace(semantic_ns, path=build_url("/", NAME, VERSION, "semantic"))
