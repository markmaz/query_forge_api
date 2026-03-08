from __future__ import annotations

import logging
from typing import Any

from app.ports.sql_executor_abc import SQLExecutor

logger = logging.getLogger(__name__)

_DEFAULT_DATASOURCE = "primary"


class AnalyticsDatasourceRegistry:
    """Registry of named ``SQLExecutor`` instances.

    Populated at application start-up from ``analytics_datasources.yaml`` via
    ``_register_analytics_registry`` in ``app/factory.py``.  Stored under
    ``app.extensions["analytics_registry"]``.

    :param executors: Mapping of datasource name → ``SQLExecutor`` instance.
    """

    def __init__(self, executors: dict[str, SQLExecutor]) -> None:
        self._executors: dict[str, SQLExecutor] = dict(executors)
        logger.debug(
            "AnalyticsDatasourceRegistry created with %d datasource(s): %s",
            len(self._executors),
            list(self._executors),
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get(self, name: str = _DEFAULT_DATASOURCE) -> SQLExecutor:
        """Return the ``SQLExecutor`` registered under *name*.

        Falls back to ``"primary"`` when *name* is ``None`` or empty.

        :param name: Datasource name.  Defaults to ``"primary"``.
        :returns: The corresponding ``SQLExecutor``.
        :raises KeyError: if the requested datasource is not registered.
        """
        effective_name = (name or _DEFAULT_DATASOURCE).strip()
        executor = self._executors.get(effective_name)
        if executor is None:
            available = sorted(self._executors)
            raise KeyError(
                f"Analytics datasource '{effective_name}' is not registered. "
                f"Available: {available}"
            )
        return executor

    def list_datasources(self) -> list[dict[str, Any]]:
        """Return a safe summary of all registered datasources.

        Credentials and internal config are never included in the output.

        :returns: List of ``{"name": str, "type": str}`` dicts, sorted by name.
        """
        result: list[dict[str, Any]] = []
        for name, executor in sorted(self._executors.items()):
            result.append({"name": name, "type": executor.get_dialect()})
        return result
