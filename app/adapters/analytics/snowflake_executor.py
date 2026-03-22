from __future__ import annotations

import logging
import re
from typing import Optional
from urllib.parse import urlparse

from app.ports.sql_executor_abc import SQLExecutor

logger = logging.getLogger(__name__)


def _normalize_account_identifier(account: str) -> str:
    """Normalise a Snowflake account input for the Python connector.

    Accepts either:
    - account identifier (e.g. ``xy12345.us-east-1`` or ``org-account``), or
    - full account URL (e.g. ``https://org-account.snowflakecomputing.com``).
    """
    raw = (account or "").strip()
    if not raw:
        return raw

    host_or_account = raw
    if "://" in raw:
        parsed = urlparse(raw)
        host_or_account = parsed.hostname or raw

    host_or_account = host_or_account.strip().split("/")[0].split(":")[0]
    suffix = ".snowflakecomputing.com"
    if host_or_account.lower().endswith(suffix):
        host_or_account = host_or_account[: -len(suffix)]

    return host_or_account.strip().lower()


def _load_private_key_pem(private_key_pem: str, private_key_passphrase: Optional[str]):
    """Load PEM private key text for Snowflake keypair authentication.

    :param private_key_pem: PEM private key contents.
    :param private_key_passphrase: Optional passphrase for the key.
    :returns: DER-encoded private key bytes suitable for ``snowflake.connector``.
    """
    from cryptography.hazmat.backends import default_backend
    from cryptography.hazmat.primitives import serialization

    passphrase_bytes: Optional[bytes] = None
    if private_key_passphrase:
        passphrase_bytes = private_key_passphrase.encode("utf-8")

    private_key = serialization.load_pem_private_key(
        private_key_pem.encode("utf-8"),
        password=passphrase_bytes,
        backend=default_backend(),
    )

    return private_key.private_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )


def _load_private_key(private_key_path: str, private_key_passphrase: Optional[str]):
    """Load a PEM private key file for Snowflake keypair authentication."""
    with open(private_key_path, "r", encoding="utf-8") as key_file:
        return _load_private_key_pem(key_file.read(), private_key_passphrase)


def _rewrite_named_params_for_snowflake(sql: str, params: Optional[dict]) -> str:
    """Convert SQLAlchemy-style ``:name`` placeholders to Snowflake ``%(name)s``.

    Query Forge compiles SQL using ``:p1`` style bind names. Snowflake's Python
    connector expects pyformat placeholders when binding a dict.
    """
    text = str(sql or "")
    if text == "" or not isinstance(params, dict) or not params:
        return text
    out = text
    for name in params.keys():
        token = str(name or "").strip()
        if token == "":
            continue
        out = re.sub(rf":{re.escape(token)}\b", f"%({token})s", out)
    return out


def _rewrite_identifier_quotes_for_snowflake(sql: str) -> str:
    """Convert backtick-quoted identifiers to Snowflake double-quoted identifiers.

    Query Forge SQL generation currently uses backticks for quoted identifiers
    (Spark/MySQL style). Snowflake requires double quotes for quoted identifiers.
    This rewrite intentionally only operates outside string literals.
    """
    text = str(sql or "")
    if "`" not in text:
        return text

    out: list[str] = []
    in_single = False
    in_double = False
    in_backtick = False
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]

        if in_single:
            out.append(ch)
            if ch == "'" and i + 1 < n and text[i + 1] == "'":
                out.append(text[i + 1])
                i += 2
                continue
            if ch == "'":
                in_single = False
            i += 1
            continue

        if in_double:
            out.append(ch)
            if ch == '"' and i + 1 < n and text[i + 1] == '"':
                out.append(text[i + 1])
                i += 2
                continue
            if ch == '"':
                in_double = False
            i += 1
            continue

        if ch == "'":
            in_single = True
            out.append(ch)
            i += 1
            continue

        if ch == '"':
            in_double = True
            out.append(ch)
            i += 1
            continue

        if ch == "`":
            in_backtick = not in_backtick
            out.append('"')
            i += 1
            continue

        if in_backtick and ch == '"':
            # Preserve literal quotes inside identifier by escaping per Snowflake rules.
            out.append('""')
            i += 1
            continue

        out.append(ch)
        i += 1

    return "".join(out)


def _is_missing_warehouse_error(exc: Exception) -> bool:
    err_no = getattr(exc, "errno", None)
    if err_no in {606, "606"}:
        return True
    text = str(exc or "").lower()
    return "no active warehouse selected" in text or "use warehouse" in text


class SnowflakeSQLExecutor(SQLExecutor):
    """Analytics executor for Snowflake.

    Opens and closes a Snowflake connection on every ``execute()`` call — no
    persistent global connection is maintained.  Supports both username/password
    authentication and keypair authentication (when ``private_key_pem`` or
    ``private_key_path`` is provided).

    :param account: Snowflake account identifier, e.g. ``xy12345.us-east-1``.
    :param user: Snowflake username.
    :param database: Default database name.
    :param warehouse: Optional virtual warehouse to use.
    :param schema: Optional default schema.
    :param authenticator: Optional Snowflake authenticator (for example,
        ``externalbrowser`` for SSO/browser login).
    :param role: Optional Snowflake role to adopt.
    :param password: Password for username/password auth.
    :param private_key_pem: PEM private key contents for keypair auth.
    :param private_key_path: Path to PEM private key file for keypair auth.
    :param private_key_passphrase: Optional passphrase for the private key.
    """

    def __init__(
        self,
        account: str,
        user: str,
        database: str,
        warehouse: Optional[str] = None,
        schema: Optional[str] = None,
        authenticator: Optional[str] = None,
        role: Optional[str] = None,
        password: Optional[str] = None,
        private_key_pem: Optional[str] = None,
        private_key_path: Optional[str] = None,
        private_key_passphrase: Optional[str] = None,
    ) -> None:
        if not account:
            raise ValueError("SnowflakeSQLExecutor: 'account' is required")
        if not user:
            raise ValueError("SnowflakeSQLExecutor: 'user' is required")
        if not database:
            raise ValueError("SnowflakeSQLExecutor: 'database' is required")
        if not password and not private_key_pem and not private_key_path and not authenticator:
            raise ValueError(
                "SnowflakeSQLExecutor: one auth method is required "
                "('password', 'private_key_pem', 'private_key_path', or 'authenticator')"
            )

        self._account = _normalize_account_identifier(account)
        self._user = user
        self._database = database
        self._warehouse = (warehouse or "").strip() or None
        self._schema = (schema or "").strip() or None
        auth = (authenticator or "").strip()
        self._authenticator = ("externalbrowser" if auth.lower() == "externalbrowser" else auth) or None
        self._role = role
        self._password = password
        self._private_key_pem = private_key_pem
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
            # FIND-022: insecure_mode must always be False.  This is the Snowflake
            # connector's default but we set it explicitly so that no YAML config
            # value can silently override it.
            "insecure_mode": False,
        }
        if self._warehouse:
            connect_kwargs["warehouse"] = self._warehouse
        if self._schema:
            connect_kwargs["schema"] = self._schema
        if self._role:
            connect_kwargs["role"] = self._role
        if self._authenticator:
            connect_kwargs["authenticator"] = self._authenticator

        if self._private_key_pem:
            connect_kwargs["private_key"] = _load_private_key_pem(
                self._private_key_pem,
                self._private_key_passphrase,
            )
        elif self._private_key_path:
            connect_kwargs["private_key"] = _load_private_key(
                self._private_key_path, self._private_key_passphrase
            )
        elif self._password:
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
                rewritten_sql = _rewrite_identifier_quotes_for_snowflake(sql)
                rewritten_sql = _rewrite_named_params_for_snowflake(rewritten_sql, params)
                cursor.execute(rewritten_sql, params)
            else:
                rewritten_sql = _rewrite_identifier_quotes_for_snowflake(sql)
                cursor.execute(rewritten_sql)

            columns = [desc[0] for desc in (cursor.description or [])]
            rows = cursor.fetchall()
            return [dict(zip(columns, row)) for row in rows]
        except Exception as exc:
            # FIND-021: log full driver exception internally; sanitize the raised
            # message so Snowflake account identifiers/hostnames are not returned
            # to callers.
            logger.exception("SnowflakeSQLExecutor.execute failed")
            err_no = getattr(exc, "errno", None)
            if err_no == 390190:
                raise RuntimeError(
                    "Analytics authentication failed: check Snowflake account identifier and authenticator settings"
                ) from exc
            if err_no == 250001:
                raise RuntimeError(
                    "Analytics authentication failed: Snowflake JWT token is invalid. "
                    "Verify the Snowflake private key configuration and "
                    "that the matching RSA public key is configured for the Snowflake user."
                ) from exc
            if _is_missing_warehouse_error(exc):
                raise RuntimeError(
                    "Analytics execution failed: no active Snowflake warehouse selected. "
                    "Set datasource config_json.warehouse (or issue USE WAREHOUSE before queries)."
                ) from exc
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
        except RuntimeError as exc:
            # Keep the execute() diagnostic, but make it explicit this happened
            # during a datasource connectivity check.
            raise RuntimeError(f"Analytics datasource connection test failed: {exc}") from exc
        except Exception as exc:
            # FIND-021: sanitized message — no account identifier or hostname.
            logger.exception("SnowflakeSQLExecutor.test_connection failed")
            raise RuntimeError("Analytics datasource connection test failed") from exc

    def get_dialect(self) -> str:
        return "snowflake"
