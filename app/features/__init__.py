from importlib import import_module

FEATURE_MODULES = [
    "app.features.auth.routes",
    "app.features.users.routes",
    "app.features.workspaces.routes",
    "app.features.admin.routes",
    "app.features.catalog.routes",
    "app.features.domains.routes",
    "app.features.skills.routes",
    "app.features.query_engine.routes",
    "app.features.saved_queries.routes",
    "app.features.forge_match.routes",
    "app.features.planner.routes",
    "app.features.ai.routes",
    "app.features.exports.routes",
    "app.features.semantic.routes",
    "app.features.ingestion.routes",
    "app.features.vector.routes",
    "app.features.data_catalog.routes",
    "app.features.data_environment.routes",
]


def register_features(api):
    for module_name in FEATURE_MODULES:
        registrar = import_module(module_name).register
        registrar(api)
