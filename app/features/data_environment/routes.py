from app.routes.data_environment import data_environment_ns

NAMESPACES = [
    (data_environment_ns, "/{NAME}/{VERSION}/data-environment"),
]
