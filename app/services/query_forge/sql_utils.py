"""SQL escaping and rendering utilities for the query_forge package.

All functions are module-level (stateless) extractions from QueryForgeService.
"""
from __future__ import annotations

import re
from typing import Any, Dict

from app.exceptions.forge_error import ForgeError

_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
INT_PARSE_ERRORS = (TypeError, ValueError)


def literal_sql(v: Any) -> str:
    """Render a Python value as a safe SQL literal."""
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, (int, float)):
        return str(v)
    s = str(v)
    s = s.replace("\\", "\\\\").replace("'", "''")
    return f"'{s}'"


def render_sql(sql: str, params: Dict[str, Any]) -> str:
    """Substitute :pN placeholders in *sql* with their rendered literal values."""
    if not sql or not params:
        return sql

    def _render_value(v: Any) -> str:
        if isinstance(v, (list, tuple, set)):
            return "(" + ", ".join(literal_sql(x) for x in v) + ")"
        return literal_sql(v)

    def _repl(match: re.Match) -> str:  # type: ignore[type-arg]
        key = match.group(0).lstrip(":")
        if key not in params:
            return match.group(0)
        return _render_value(params[key])

    return re.sub(r":p\d+", _repl, sql)


def safe_ident(s: str) -> str:
    """Assert that *s* is a valid bare SQL identifier and return it unchanged."""
    if not s or not isinstance(s, str) or not _IDENT_RE.match(s):
        raise ForgeError(f"Invalid identifier: {s}", status_code=400)
    return s


def safe_alias(s: str) -> str:
    """Return a SQL-safe alias, backtick-quoting if necessary."""
    if s is None or not isinstance(s, str):
        raise ForgeError("Invalid alias", status_code=400)
    v = s.strip()
    if not v:
        raise ForgeError("Invalid alias", status_code=400)
    if _IDENT_RE.match(v):
        return v
    if any(ord(ch) < 32 for ch in v):
        raise ForgeError("Invalid alias (control characters)", status_code=400)
    v = v.replace("`", "``")
    return f"`{v}`"


def dp_ident(qf_out_name: str) -> str:
    """Internal DataPrep column identifier, e.g. 'claim type' → '__dp_claim_type'."""
    base = re.sub(r"[^A-Za-z0-9_]+", "_", (qf_out_name or "").strip())
    if not base:
        base = "col"
    if base[0].isdigit():
        base = f"c_{base}"
    return safe_ident(f"__dp_{base}")


def physical_col_expr(
    col_name: str,
    *,
    qf_using_prep: bool,
    qf_base_alias: str,
    alias: "str | None",
) -> str:
    """Return the physical SQL expression for a bare column name."""
    if not col_name or not isinstance(col_name, str):
        raise ForgeError("Invalid columnName", status_code=400)
    if "." in col_name:
        raise ForgeError(f"Qualified column names are not allowed: {col_name}", status_code=400)
    if qf_using_prep:
        return safe_ident(col_name)
    base = alias or qf_base_alias
    return f"{safe_ident(base)}.{safe_ident(col_name)}"


def col_expr(
    key_or_ref: Any,
    derived_by_exprid: Dict[str, Any],
    derived_by_name: Dict[str, Any],
    rewrite_by_colname: Dict[str, Any],
    rewrite_by_modelid: Dict[Any, Any],
    qf_using_prep: bool,
    qf_base_alias: str,
    alias_by_wt: Dict[int, str],
    *,
    rewrite_by_wt_col: "Dict[Any, Any] | None" = None,
) -> str:
    """Resolve a column key-or-reference dict to a SQL expression."""
    if rewrite_by_wt_col is None:
        rewrite_by_wt_col = {}
    if isinstance(key_or_ref, str):
        cn = key_or_ref.strip()
        if "." in cn:
            raise ForgeError(f"Qualified column names are not allowed: {cn}", status_code=400)
        if qf_using_prep and cn in rewrite_by_colname:
            return rewrite_by_colname[cn]
        return physical_col_expr(cn, qf_using_prep=qf_using_prep, qf_base_alias=qf_base_alias, alias=None)

    if not isinstance(key_or_ref, dict):
        raise ForgeError("Invalid column reference", status_code=400)

    expr_id = key_or_ref.get("exprId")
    cn = key_or_ref.get("columnName")
    mid = key_or_ref.get("modelColumnId")
    wt_id = key_or_ref.get("workspaceTableId")

    if expr_id and expr_id in derived_by_exprid:
        return derived_by_exprid[expr_id]
    if cn and cn in derived_by_name:
        return derived_by_name[cn]
    if not cn or not isinstance(cn, str):
        raise ForgeError("Invalid columnName", status_code=400)
    if "." in cn:
        raise ForgeError(f"Qualified column names are not allowed: {cn}", status_code=400)

    if qf_using_prep:
        if isinstance(mid, int) and mid in rewrite_by_modelid:
            return rewrite_by_modelid[mid]
        if wt_id is not None:
            try:
                wt_id_int = int(wt_id)
            except INT_PARSE_ERRORS:
                wt_id_int = None
            if wt_id_int is not None:
                mapped = rewrite_by_wt_col.get((wt_id_int, cn))
                if mapped:
                    return mapped
        if cn in rewrite_by_colname:
            return rewrite_by_colname[cn]

    wt_alias: "str | None" = None
    if wt_id is not None:
        try:
            wt_id_int = int(wt_id)
        except INT_PARSE_ERRORS:
            raise ForgeError("Invalid workspaceTableId", status_code=400)
        wt_alias = alias_by_wt.get(wt_id_int)
        if not wt_alias:
            raise ForgeError("workspaceTableId is not in domain", status_code=400)
    return physical_col_expr(cn, qf_using_prep=qf_using_prep, qf_base_alias=qf_base_alias, alias=wt_alias)
