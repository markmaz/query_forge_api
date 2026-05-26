from __future__ import annotations

import re
from typing import Any, Mapping

from app.features.flowforge.reporting.manifest import REPORTING_DOMAINS

_CREATE_VIEW_RE = re.compile(
    r"CREATE\s+OR\s+REPLACE\s+VIEW\s+(?P<name>[A-Za-z0-9_]+)\s+AS\s+SELECT\s+(?P<select>.*?)\s+FROM\s+",
    re.IGNORECASE | re.DOTALL,
)
_ALIAS_RE = re.compile(r"\bAS\s+([A-Za-z_][A-Za-z0-9_]*)\s*$", re.IGNORECASE)
_IDENTIFIER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*$")


def audit_reporting_read_model_sql(
    migration_sql: str,
    *,
    domains: list[dict[str, Any]] | None = None,
) -> list[str]:
    """Validate FlowForge reporting manifests against read-model SQL text."""
    errors: list[str] = []
    view_columns = extract_reporting_view_columns(migration_sql)
    for domain in domains or REPORTING_DOMAINS:
        domain_key = str(domain.get("domain_key") or "<unknown>")
        read_model = str(domain.get("read_model") or "")
        columns = view_columns.get(read_model)
        if columns is None:
            errors.append(f"{domain_key}: read model {read_model} is missing from migration SQL")
            continue
        required_fields = _required_manifest_fields(domain)
        for field in sorted(required_fields):
            if field not in columns:
                errors.append(f"{domain_key}: field {field} is not exposed by {read_model}")
        for field in sorted(str(value) for value in domain.get("sensitive_excluded_fields") or []):
            if field in columns:
                errors.append(f"{domain_key}: sensitive field {field} is exposed by {read_model}")
    return errors


def extract_reporting_view_columns(migration_sql: str) -> dict[str, set[str]]:
    view_columns: dict[str, set[str]] = {}
    for match in _CREATE_VIEW_RE.finditer(migration_sql):
        view_name = match.group("name")
        view_columns[view_name] = _select_columns(match.group("select"))
    return view_columns


def _required_manifest_fields(domain: Mapping[str, Any]) -> set[str]:
    fields: set[str] = set()
    for name in ("workspace_scope_field", "mode_field"):
        value = str(domain.get(name) or "").strip()
        if value:
            fields.add(value)
    fields.update(str(value) for value in domain.get("time_fields") or [])
    fields.update(str(value) for value in domain.get("identifiers") or [])
    fields.update(str(field.get("field")) for field in domain.get("default_filters") or [] if field.get("field"))
    fields.update(str(field.get("key")) for field in domain.get("dimensions") or [] if field.get("key"))
    return fields


def _select_columns(select_sql: str) -> set[str]:
    columns: set[str] = set()
    for expression in _split_select_expressions(select_sql):
        column = _column_name(expression)
        if column:
            columns.add(column)
    return columns


def _split_select_expressions(select_sql: str) -> list[str]:
    expressions: list[str] = []
    current: list[str] = []
    depth = 0
    for char in select_sql:
        if char == "(":
            depth += 1
        elif char == ")" and depth:
            depth -= 1
        if char == "," and depth == 0:
            expressions.append("".join(current).strip())
            current = []
            continue
        current.append(char)
    if current:
        expressions.append("".join(current).strip())
    return expressions


def _column_name(expression: str) -> str | None:
    cleaned = expression.strip()
    alias_match = _ALIAS_RE.search(cleaned)
    if alias_match:
        return alias_match.group(1)
    tail = cleaned.rsplit(".", 1)[-1]
    identifier_match = _IDENTIFIER_RE.search(tail)
    return identifier_match.group(0) if identifier_match else None
