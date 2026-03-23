from __future__ import annotations


class LLMUnavailableError(Exception):
    """Raised when no LLM is configured for the workspace."""
    pass
