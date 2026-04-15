from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping

from app.exceptions.forge_error import ForgeError

GLOBAL_WORKSPACE_SCOPE_TYPES = frozenset({"global", "workspace"})
DOMAIN_POLICY_SCOPE_TYPES = frozenset({"global", "workspace", "global_domain", "workspace_domain"})


def require_global_workspace_scope(*, scope_type: str) -> str:
    token = str(scope_type or "").strip().lower()
    if token not in GLOBAL_WORKSPACE_SCOPE_TYPES:
        raise ForgeError("Only global and workspace policy scopes are supported for this policy family.", status_code=400)
    return token


def require_supported_scope(
    *,
    scope_type: str,
    allowed_scope_types: Iterable[str],
    family_label: str,
) -> str:
    token = str(scope_type or "").strip().lower()
    allowed = {str(item or "").strip().lower() for item in allowed_scope_types if str(item or "").strip()}
    if token not in allowed:
        allowed_text = ", ".join(sorted(allowed))
        raise ForgeError(
            f"Only {allowed_text} policy scopes are supported for {family_label}.",
            status_code=400,
        )
    return token


def global_workspace_scope_rank(scope_type: str) -> int:
    token = str(scope_type or "").strip().lower()
    return {"workspace": 2, "global": 1}.get(token, 0)


def scoped_policy_rank(scope_type: str) -> int:
    token = str(scope_type or "").strip().lower()
    return {
        "workspace_domain": 4,
        "workspace": 3,
        "global_domain": 2,
        "global": 1,
    }.get(token, 0)


def global_workspace_query_predicate(*, workspace_column: str = "scope_workspace_id") -> str:
    return f"""
        (
          scope_type = 'global'
          OR (scope_type = 'workspace' AND {workspace_column} = :workspace_id)
        )
    """.strip()


def scoped_query_predicate(
    *,
    include_base_domain: bool = False,
    workspace_column: str = "scope_workspace_id",
    base_domain_column: str = "scope_base_domain_id",
) -> str:
    clauses = [
        "scope_type = 'global'",
        f"(scope_type = 'workspace' AND {workspace_column} = :workspace_id)",
    ]
    if include_base_domain:
        clauses.extend(
            [
                f"(:base_domain_id IS NOT NULL AND scope_type = 'global_domain' AND {base_domain_column} = :base_domain_id)",
                (
                    f"(:base_domain_id IS NOT NULL AND scope_type = 'workspace_domain' "
                    f"AND {workspace_column} = :workspace_id AND {base_domain_column} = :base_domain_id)"
                ),
            ]
        )
    return "(\n  " + "\n  OR ".join(clauses) + "\n)".strip()


def sort_and_dedupe_global_workspace_policies(rows: Iterable[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []
    for row in rows:
        payload = dict(row)
        payload["scope_rank"] = global_workspace_scope_rank(str(payload.get("scope_type") or ""))
        normalized.append(payload)

    normalized.sort(
        key=lambda row: (
            -int(row.get("scope_rank") or 0),
            int(row.get("priority") or 100),
            -(0 if bool(row.get("_seeded")) else 1),
            int(row.get("id") or 0),
        )
    )

    deduped: List[Dict[str, Any]] = []
    seen_keys: set[str] = set()
    for row in normalized:
        policy_key = str(row.get("policy_key") or "").strip()
        if policy_key == "" or policy_key in seen_keys:
            continue
        seen_keys.add(policy_key)
        deduped.append(row)
    return deduped


def sort_and_dedupe_scoped_policies(rows: Iterable[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []
    for row in rows:
        payload = dict(row)
        payload["scope_rank"] = scoped_policy_rank(str(payload.get("scope_type") or ""))
        normalized.append(payload)

    normalized.sort(
        key=lambda row: (
            -int(row.get("scope_rank") or 0),
            int(row.get("priority") or 100),
            -(0 if bool(row.get("_seeded")) else 1),
            int(row.get("id") or 0),
        )
    )

    deduped: List[Dict[str, Any]] = []
    seen_keys: set[str] = set()
    for row in normalized:
        policy_key = str(row.get("policy_key") or "").strip()
        if policy_key == "" or policy_key in seen_keys:
            continue
        seen_keys.add(policy_key)
        deduped.append(row)
    return deduped


def annotate_effective_rows(rows: Iterable[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    visible: List[Dict[str, Any]] = []
    for row in rows:
        payload = dict(row)
        payload["scope_rank"] = global_workspace_scope_rank(str(payload.get("scope_type") or ""))
        visible.append(payload)

    visible.sort(
        key=lambda row: (
            -int(row.get("scope_rank") or 0),
            int(row.get("priority") or 100),
            -(0 if bool(row.get("is_seeded")) else 1),
            int(row.get("id") or 0),
        )
    )
    effective_keys: set[str] = set()
    for row in visible:
        policy_key = str(row.get("policy_key") or "").strip()
        row["is_effective"] = policy_key != "" and policy_key not in effective_keys
        if row["is_effective"] and policy_key:
            effective_keys.add(policy_key)
    return visible


def annotate_effective_scoped_rows(rows: Iterable[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    visible: List[Dict[str, Any]] = []
    for row in rows:
        payload = dict(row)
        payload["scope_rank"] = scoped_policy_rank(str(payload.get("scope_type") or ""))
        visible.append(payload)

    visible.sort(
        key=lambda row: (
            -int(row.get("scope_rank") or 0),
            int(row.get("priority") or 100),
            -(0 if bool(row.get("is_seeded")) else 1),
            int(row.get("id") or 0),
        )
    )
    effective_keys: set[str] = set()
    for row in visible:
        policy_key = str(row.get("policy_key") or "").strip()
        row["is_effective"] = policy_key != "" and policy_key not in effective_keys
        if row["is_effective"] and policy_key:
            effective_keys.add(policy_key)
    return visible
