from app.features.flowforge.routes import flowforge_ns


def register(api) -> None:
    from app.api_config import NAME, VERSION, build_url

    api.add_namespace(flowforge_ns, path=build_url("/", NAME, VERSION, "flowforge"))
