from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from app.exceptions.forge_error import ForgeError
from app.services.domain_resolution.models import DomainPlanJoin, DomainPlanTable, safe_fqn

ALLOWED_POLICIES = frozenset({"DEDUP_PRIMARY_FIRST", "SHOW_ALL_QUALIFIED"})
ALLOWED_FILTER_MODES = frozenset({"AUTO", "WHERE", "EXISTS"})
ALLOWED_CARDINALITY = frozenset({"ONE", "MANY"})
JOIN_SPEC_PARSE_ERRORS = (json.JSONDecodeError,)


def normalize_alias(alias: Optional[str]) -> Optional[str]:
    if alias is None:
        return None
    cleaned = alias.strip()
    if not cleaned:
        return None
    from app.services.domain_resolution.models import IDENT

    if not IDENT.match(cleaned):
        raise ForgeError(f"Unsafe table alias: {cleaned}", status_code=400)
    return cleaned


def normalize_policy(value: Any) -> str:
    policy = str(value or "DEDUP_PRIMARY_FIRST").strip().upper()
    if policy not in ALLOWED_POLICIES:
        raise ForgeError("Invalid column_name_policy for domain", status_code=400)
    return policy


def build_plan_tables(table_rows: List[Dict[str, Any]]) -> tuple[List[DomainPlanTable], Dict[int, str]]:
    tables: List[DomainPlanTable] = []
    alias_by_id: Dict[int, str] = {}
    alias_seen: set[str] = set()
    next_alias = 0

    for row in table_rows:
        workspace_table_id = int(row["workspace_table_id"])
        explicit_alias = normalize_alias(row.get("table_alias"))
        full_name = safe_fqn(str(row["full_name"]))

        filter_mode = str(row.get("filter_mode") or "AUTO").strip().upper()
        if filter_mode not in ALLOWED_FILTER_MODES:
            raise ForgeError(f"Invalid filter_mode for table {workspace_table_id}", status_code=400)

        cardinality = str(row.get("cardinality") or "ONE").strip().upper()
        if cardinality not in ALLOWED_CARDINALITY:
            raise ForgeError(f"Invalid cardinality for table {workspace_table_id}", status_code=400)

        assigned_alias = explicit_alias if explicit_alias and explicit_alias not in alias_seen else None
        if assigned_alias is None:
            while True:
                candidate = f"t{next_alias}"
                next_alias += 1
                if candidate not in alias_seen:
                    assigned_alias = candidate
                    break

        alias_seen.add(assigned_alias)
        alias_by_id[workspace_table_id] = assigned_alias

        tables.append(
            DomainPlanTable(
                workspace_table_id=workspace_table_id,
                full_name=full_name,
                alias=assigned_alias,
                table_alias=explicit_alias,
                is_primary=bool(row.get("is_primary")),
                sort_order=int(row.get("sort_order") or 0),
                filter_mode=filter_mode,
                cardinality=cardinality,
            )
        )

    return tables, alias_by_id


def to_plan_join(row: Dict[str, Any]) -> DomainPlanJoin:
    raw_spec = row.get("join_spec_json")
    if isinstance(raw_spec, str):
        try:
            parsed_spec = json.loads(raw_spec)
        except JOIN_SPEC_PARSE_ERRORS as exc:
            raise ForgeError("Invalid join_spec_json", status_code=400) from exc
    elif isinstance(raw_spec, dict):
        parsed_spec = raw_spec
    else:
        parsed_spec = {}

    return DomainPlanJoin(
        join_id=str(row.get("id")),
        from_workspace_table_id=int(row["from_workspace_table_id"]),
        to_workspace_table_id=int(row["to_workspace_table_id"]),
        join_type=str(row.get("join_type") or "").upper(),
        join_spec=parsed_spec if isinstance(parsed_spec, dict) else {},
        sort_order=int(row.get("sort_order") or 0),
    )
