from __future__ import annotations

import re
from typing import Iterable

from app.exceptions.forge_error import ForgeError


DISALLOWED_CLIENT_SQL_FIELDS = frozenset(
    {
        "sql",
        "params",
        "countSql",
        "qf_count_sql",
        "sqlRendered",
        "qf_rendered_sql",
        "warehouse_id",
        "catalog",
        "schema",
    }
)

_FORBIDDEN_SQL_KEYWORDS = (
    "INSERT",
    "UPDATE",
    "DELETE",
    "MERGE",
    "DROP",
    "ALTER",
    "CREATE",
    "TRUNCATE",
    "CALL",
    "EXECUTE",
    "GRANT",
    "REVOKE",
    "OPTIMIZE",
    "VACUUM",
    "USE",
    "COPY",
)


def assert_no_disallowed_client_sql_fields(
    payload: dict,
    *,
    disallowed_fields: Iterable[str] = DISALLOWED_CLIENT_SQL_FIELDS,
) -> None:
    disallowed = {str(field) for field in disallowed_fields}
    present = sorted(field for field in payload.keys() if field in disallowed)
    if present:
        raise ForgeError(
            "Raw SQL fields are not allowed in this endpoint: " + ", ".join(present),
            status_code=400,
        )


def assert_read_only_sql_statement(sql: str, *, context: str = "SQL statement") -> None:
    source = str(sql or "").strip()
    if not source:
        raise ForgeError(f"{context} is required", status_code=400)

    canonical = _canonicalize_sql(source)

    # Keep to a single statement to avoid piggy-backing side effects.
    if ";" in canonical:
        raise ForgeError(f"{context} must be a single SELECT statement", status_code=400)

    if not (canonical.startswith("SELECT ") or canonical.startswith("WITH ")):
        raise ForgeError(f"{context} must start with SELECT or WITH", status_code=400)

    if " SELECT " not in f" {canonical} ":
        raise ForgeError(f"{context} must contain a SELECT clause", status_code=400)

    forbidden_pattern = r"\b(" + "|".join(_FORBIDDEN_SQL_KEYWORDS) + r")\b"
    if re.search(forbidden_pattern, canonical):
        raise ForgeError(f"{context} must be read-only", status_code=400)


def _canonicalize_sql(sql: str) -> str:
    out = sql
    out = re.sub(r"/\*.*?\*/", " ", out, flags=re.DOTALL)
    out = re.sub(r"--[^\n]*", " ", out)
    out = re.sub(r"'(?:''|[^'])*'", "''", out)
    out = re.sub(r'"(?:""|[^"])*"', '""', out)
    out = re.sub(r"`(?:``|[^`])*`", "``", out)
    out = re.sub(r"\s+", " ", out)
    return out.strip().upper()
