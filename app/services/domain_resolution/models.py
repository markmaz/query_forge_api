from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Optional

from app.exceptions.forge_error import ForgeError

IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def safe_fqn(full_name: str) -> str:
    if not full_name or not isinstance(full_name, str):
        raise ForgeError("Invalid resolved table name", status_code=400)

    parts = full_name.split(".")
    if len(parts) not in (2, 3):
        raise ForgeError(f"Invalid table full_name: {full_name}", status_code=400)

    for part in parts:
        if not IDENT.match(part):
            raise ForgeError(f"Unsafe identifier in full_name: {full_name}", status_code=400)

    return full_name


@dataclass(frozen=True)
class ResolvedDomainFrom:
    workspace_table_id: int
    full_name: str


@dataclass(frozen=True)
class DomainPlanTable:
    workspace_table_id: int
    full_name: str
    alias: str
    table_alias: Optional[str]
    is_primary: bool
    sort_order: int
    filter_mode: str
    cardinality: str


@dataclass(frozen=True)
class DomainPlanJoin:
    join_id: str
    from_workspace_table_id: int
    to_workspace_table_id: int
    join_type: str
    join_spec: Dict[str, object]
    sort_order: int


@dataclass(frozen=True)
class DomainPlan:
    primary: DomainPlanTable
    tables: List[DomainPlanTable]
    joins: List[DomainPlanJoin]
    alias_by_workspace_table_id: Dict[int, str]
    column_name_policy: str
