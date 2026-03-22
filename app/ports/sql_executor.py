# Re-exports for backwards compatibility — canonical definitions live in app.adapters.query_port
from app.adapters.query_port import ForgeExecResult, ForgeQueryPort, ForgeQueryTx

__all__ = ["ForgeExecResult", "ForgeQueryPort", "ForgeQueryTx"]
