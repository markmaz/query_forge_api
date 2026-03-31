from importlib import import_module

FEATURE_REGISTRAR_MODULES = [
    "app.features.auth.register",
    "app.features.users.register",
    "app.features.workspaces.register",
    "app.features.admin.register",
    "app.features.catalog.register",
    "app.features.skills.register",
    "app.features.query_engine.register",
    "app.features.saved_queries.register",
    "app.features.forge_match.register",
    "app.features.planner.register",
    "app.features.ai.register",
    "app.features.exports.register",
    "app.features.semantic.register",
    "app.features.ingestion.register",
    "app.features.vector.register",
    "app.features.data_catalog.register",
    "app.features.data_environment.register",
]


def register_features(api):
    for module_name in FEATURE_REGISTRAR_MODULES:
        registrar = import_module(module_name).register
        registrar(api)
