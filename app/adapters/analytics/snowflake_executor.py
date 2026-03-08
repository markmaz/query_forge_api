from __future__ import annotations

import logging
from typing import Optional

from app.ports.sql_executor_abc import SQLExecutor

logger = logging.getLogger(__name__)


def _load_private_key(private_key_path: str, private_key_passphrase: Optional[str]):
    """Load a PEM private key for Snowflake keypair authentication.

    :param private_key_path: Filesystem path to the PEM private key file.
    :param private_key_passphrase: Optional passphrase for the key file.
    :returns: DER-encoded private key bytes suitable for ``snowflake.connector``.
    """
    from cryptography.hazmat.backends import default_backend
    from cryptography.hazmat.primitives import serialization

    passphrase_bytes: Optional[bytes] = None
    if private_key_passphrase:
        passphrase_bytes = private_key_passphrase.encode("utf-8")

    with open(private_key_path, "rb") as key_file:
        private_key = serialization.load_pem_private_key(
            key_file.read(),
            password=passphrase_bytes,
            backend=default_backend(),
        )

    return private_key.private_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )


class SnowflakeSQLExecutor(SQLExecutor):
    """Analytics executor for Snowflake.

    Opens and closes a Snowflake connection on every ``execute()`` call — no
    persistent global connection is maintained.  Supports both username/password
    authentication and keypair authentication (when ``private_key_path`` is provided).

    :param account: Snowflake account identifier, e.g. ``xy12345.us-east-1``.
    :param user: Snowflake username.
    :param database: Default database name.
    :param warehouse: Virtual warehouse to use.
    :param role: Optional Snowflake role to adopt.
    :param password: Password for username/password auth.
    :param private_key_path: Path to PEM private key file for keypair auth.
    :param private_key_passphrase: Optional passphrase for the private key.
    """

    def __init__(
        self,
        account: str,
        user: str,
        database: str,
        warehouse: str,
        role: Optional[str] = None,
        password: Optional[str] = None,
        private_key_path: Optional[str] = None,
        private_key_passphrase: Optional[str] = None,
    ) -> None:
        if not account:
            raise ValueError("SnowflakeSQLExecutor: 'account' is required")
        if not user:
            raise ValueError("SnowflakeSQLExecutor: 'user' is required")
        if not database:
            raise ValueError("SnowflakeSQLExecutor: 'database' is required")
        if not warehouse:
            raise ValueError("SnowflakeSQLExecutor: 'warehouse' is required")
        if not password and not private_key_path:
            raise ValueError(
                "SnowflakeSQLExecutor: either 'password' or 'private_key_path' is required"
            )

        self._account = account
        self._user = user
        self._database = database
        self._warehouse = warehouse
        self._role = role
        self._password = password
        self._private_key_path = private_key_path
        self._private_key_passphrase = private_key_passphrase

        logger.debug(
            "SnowflakeSQLExecutor initialised: account=%s user=%s database=%s warehouse=%s",
            self._account,
            self._user,
            self._database,
            self._warehouse,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _connect(self):
        """Open a new Snowflake connection and return it."""
        import snowflake.connector  # type: ignore[import]

        connect_kwargs: dict = {
            "account": self._account,
            "user": self._user,
            "database": self._database,
            "warehouse": self._warehouse,
            # FIND-022: insecure_mode must always be False.  This is the Snowflake
            # connector's default but we set it explicitly so that no YAML config
            # value can silently override it.
            "insecure_mode": False,
        }
        if self._role:
            connect_kwargs["role"] = self._role

        if self._private_key_path:
            connect_kwargs["private_key"] = _load_private_key(
                self._private_key_path, self._private_key_passphrase
            )
        else:
            connect_kwargs["password"] = self._password

        return snowflake.connector.connect(**connect_kwargs)

    # ------------------------------------------------------------------
    # SQLExecutor interface
    # ------------------------------------------------------------------

    def execute(self, sql: str, params: Optional[dict] = None) -> list[dict]:
        """Execute *sql* against Snowflake, returning rows as dicts.

        A fresh connection is opened and closed for each call.

        :param sql: SQL statement to execute.
        :param params: Optional named parameters; passed as the ``params`` keyword argument
            to the Snowflake cursor ``execute`` call.
        :returns: List of row dicts.
        :raises RuntimeError: on Snowflake execution failure.
        """
        logger.debug("SnowflakeSQLExecutor.execute: sql_len=%d", len(sql))
        conn = None
        cursor = None
        try:
            conn = self._connect()
            cursor = conn.cursor()

            # Snowflake connector accepts params as a sequence for ``%s`` or a dict for ``%(name)s``
            if params:
                cursor.execute(sql, params)
            else:
                cursor.execute(sql)

            columns = [desc[0] for desc in (cursor.description or [])]
            rows = cursor.fetchall()
            return [dict(zip(columns, row)) for row in rows]
        except Exception as exc:
            # FIND-021: log full driver exception internally; sanitize the raised
            # message so Snowflake account identifiers/hostnames are not returned
            # to callers.
            logger.exception("SnowflakeSQLExecutor.execute failed")
            raise RuntimeError("Analytics query execution failed") from exc
        finally:
            if cursor is not None:
                try:
                    cursor.close()
                except Exception:
                    pass
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass

    def test_connection(self) -> None:
        """Verify connectivity by running ``SELECT CURRENT_VERSION()``."""
        try:
            self.execute("SELECT CURRENT_VERSION() AS _ping")
        except Exception as exc:
            # FIND-021: sanitized message — no account identifier or hostname.
            logger.exception("SnowflakeSQLExecutor.test_connection failed")
            raise RuntimeError("Analytics datasource connection test failed") from exc

    def get_dialect(self) -> str:
        return "snowflake"
