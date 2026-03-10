from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional


class SQLExecutor(ABC):
    """Abstract base class for analytics SQL executors.

    Implementors provide a uniform ``execute`` / ``test_connection`` / ``get_dialect``
    surface regardless of the underlying data warehouse (Databricks, Snowflake, MySQL, …).

    This is intentionally separate from ``ForgeQueryPort`` (Protocol) which covers the
    full application‑level executor contract used by legacy and ORM paths.  The analytics
    adapter pattern uses only this lighter interface.
    """

    @abstractmethod
    def execute(self, sql: str, params: Optional[dict] = None) -> list[dict]:
        """Execute *sql* and return each row as a plain ``dict``.

        :param sql: The SQL statement to execute.
        :param params: Optional named parameters; passed through to the underlying driver.
        :returns: A list of rows, each represented as ``{column_name: value}``.
        :raises RuntimeError: on execution failure.
        """

    @abstractmethod
    def test_connection(self) -> None:
        """Verify that the datasource is reachable.

        :raises RuntimeError: if the connection cannot be established.
        """

    @abstractmethod
    def get_dialect(self) -> str:
        """Return a lowercase string identifying the SQL dialect, e.g. ``"databricks"``.

        :returns: dialect name string.
        """
