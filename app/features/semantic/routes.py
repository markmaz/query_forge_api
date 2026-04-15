from app.api_config import NAME, VERSION, build_url

from .semantic_concepts_api import (
    semantic_concept_aliases_ns,
    semantic_concept_column_maps_ns,
    semantic_concepts_ns,
    semantic_value_aliases_ns,
)
from .semantic_mappings_api import semantic_mappings_ns
from .semantic_plan_api import semantic_ns
from .semantic_registry_api import semantic_registry_ns
from .semantic_relationships_api import semantic_relationships_ns
from .semantic_suggestions_api import semantic_suggestions_ns


def register(api):
    api.add_namespace(semantic_concepts_ns, path=build_url("/", NAME, VERSION, "semantic", "concepts"))
    api.add_namespace(semantic_concept_aliases_ns, path=build_url("/", NAME, VERSION, "semantic", "concept-aliases"))
    api.add_namespace(semantic_value_aliases_ns, path=build_url("/", NAME, VERSION, "semantic", "value-aliases"))
    api.add_namespace(semantic_concept_column_maps_ns, path=build_url("/", NAME, VERSION, "semantic", "concept-column-maps"))
    api.add_namespace(semantic_mappings_ns, path=build_url("/", NAME, VERSION, "semantic", "mappings"))
    api.add_namespace(semantic_registry_ns, path=build_url("/", NAME, VERSION, "semantic", "registry"))
    api.add_namespace(semantic_relationships_ns, path=build_url("/", NAME, VERSION, "semantic", "relationships"))
    api.add_namespace(semantic_suggestions_ns, path=build_url("/", NAME, VERSION, "semantic", "suggestions"))
    api.add_namespace(semantic_ns, path=build_url("/", NAME, VERSION, "semantic"))
