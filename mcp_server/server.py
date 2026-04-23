from __future__ import annotations

from mcp.server.fastmcp import FastMCP
from starlette.middleware.cors import CORSMiddleware

from .auth import BearerTokenMiddleware
from .config import MCPSettings
from .dependencies import MCPDependencies
from .resource_registry import register_resources
from .tool_registry import register_tools


def create_mcp_server(
    *,
    settings: MCPSettings | None = None,
    dependencies: MCPDependencies | None = None,
) -> FastMCP:
    resolved_settings = settings or MCPSettings.from_env()
    resolved_dependencies = dependencies or MCPDependencies(settings=resolved_settings)
    resolved_dependencies.settings = resolved_settings

    mcp = FastMCP(
        name=resolved_settings.server_name,
        instructions=(
            "QueryForge MCP exposes governed semantic query capabilities. "
            "It does not execute arbitrary SQL and enforces workspace and domain access."
        ),
        host=resolved_settings.host,
        port=resolved_settings.port,
        mount_path=resolved_settings.mount_path,
        streamable_http_path=resolved_settings.streamable_http_path,
        stateless_http=resolved_settings.stateless_http,
        json_response=resolved_settings.json_response,
        debug=resolved_settings.debug,
        log_level="DEBUG" if resolved_settings.debug else "INFO",
    )
    register_tools(mcp, resolved_dependencies)
    register_resources(mcp, resolved_dependencies)
    return mcp


def create_streamable_http_app(
    *,
    settings: MCPSettings | None = None,
    dependencies: MCPDependencies | None = None,
):
    resolved_settings = settings or MCPSettings.from_env()
    mcp = create_mcp_server(settings=resolved_settings, dependencies=dependencies)
    app = mcp.streamable_http_app()
    app.add_middleware(BearerTokenMiddleware)
    if resolved_settings.allowed_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(resolved_settings.allowed_origins),
            allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
            allow_headers=["Authorization", "Content-Type", "Mcp-Session-Id"],
            expose_headers=["Mcp-Session-Id"],
        )
    return app


def main() -> None:
    settings = MCPSettings.from_env()
    mcp = create_mcp_server(settings=settings)
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
