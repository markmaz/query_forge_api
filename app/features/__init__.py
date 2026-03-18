from .auth import register as register_auth
from .users import register as register_users
from .workspaces import register as register_workspaces
from .admin import register as register_admin
from .catalog import register as register_catalog
from .skills import register as register_skills
from .query_engine import register as register_query_engine
from .saved_queries import register as register_saved_queries
from .forge_match import register as register_forge_match
from .planner import register as register_planner
from .ai import register as register_ai
from .exports import register as register_exports
from .semantic import register as register_semantic
from .ingestion import register as register_ingestion
from .vector import register as register_vector
from .data_catalog import register as register_data_catalog
from .data_environment import register as register_data_environment

FEATURE_REGISTRARS = [
    register_auth,
    register_users,
    register_workspaces,
    register_admin,
    register_catalog,
    register_skills,
    register_query_engine,
    register_saved_queries,
    register_forge_match,
    register_planner,
    register_ai,
    register_exports,
    register_semantic,
    register_ingestion,
    register_vector,
    register_data_catalog,
    register_data_environment,
]


def register_features(api):
    for registrar in FEATURE_REGISTRARS:
        registrar(api)
