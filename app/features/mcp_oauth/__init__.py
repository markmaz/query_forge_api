"""MCP OAuth discovery and authorization wrapper feature."""

from .routes import mcp_oauth_ns, register, register_well_known_routes

__all__ = ["mcp_oauth_ns", "register", "register_well_known_routes"]
