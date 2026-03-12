from __future__ import annotations

import json
import re
from collections import deque
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.exceptions.forge_error import ForgeError
from app.ports.sql_executor import ForgeQueryPort

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_ALLOWED_POLICIES = frozenset({"DEDUP_PRIMARY_FIRST", "SHOW_ALL_QUALIFIED"})
_ALLOWED_FILTER_MODES = frozenset({"AUTO", "WHERE", "EXISTS"})
_ALLOWED_CARDINALITY = frozenset({"ONE", "MANY"})


def _safe_fqn(full_name: str) -> str:
    if not full_name or not isinstance(full_name, str):
        raise ForgeError("Invalid resolved table name", status_code=400)

    parts = full_name.split(".")
    if len(parts) not in (2, 3):
        raise ForgeError(f"Invalid table full_name: {full_name}", status_code=400)

    for part in parts:
        if not _IDENT.match(part):
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


class DomainResolver:
    """
    Resolve a domain to workspace tables and joins.

    lookup order for resolve():
      1) explicit domain_workspace_table mapping
    """

    def __init__(self, *, workspace_id: str, allow_ambiguous: bool = False, sql: Optional[ForgeQueryPort] = None):
        self._workspace_id = workspace_id
        self._allow_ambiguous = bool(allow_ambiguous)
        self._sql = sql or ForgeMetaSQL()

    def resolve_plan(self, domain_id: int) -> DomainPlan:
        domain_id = self._coerce_domain_id(domain_id)

        table_rows = self._sql.execute_query_mappings(
            """
            SELECT
              dwt.workspace_table_id,
              dwt.table_alias,
              dwt.is_primary,
              dwt.sort_order,
              dwt.filter_mode,
              dwt.cardinality,
              d.column_name_policy,
              wt.full_name
            FROM domain_workspace_table dwt
            JOIN domain d
              ON d.id = dwt.domain_id
             AND d.workspace_id = :ws
             AND d.is_active = 1
            JOIN workspace_table wt
              ON wt.id = dwt.workspace_table_id
             AND wt.workspace_id = :ws
             AND wt.exists_in_dbx = 1
            WHERE dwt.domain_id = :did
            ORDER BY dwt.is_primary DESC, dwt.sort_order ASC, wt.id ASC
            """,
            {"did": domain_id, "ws": self._workspace_id},
        )
        join_rows = self._sql.execute_query_mappings(
            """
            SELECT
              id,
              from_workspace_table_id,
              to_workspace_table_id,
              join_type,
              join_spec_json,
              sort_order
            FROM domain_table_join
            WHERE domain_id = :did
              AND is_active = 1
            ORDER BY sort_order ASC, id ASC
            """,
            {"did": domain_id},
        )

        if not table_rows:
            raise ForgeError(f"Unknown domainId {domain_id} for workspace {self._workspace_id}", status_code=404)

        policy = self._normalize_policy(table_rows[0].get("column_name_policy"))
        tables, alias_map = self._build_plan_tables(table_rows)

        if len(tables) > 1 and policy == "SHOW_ALL_QUALIFIED":
            missing_alias = [t.workspace_table_id for t in tables if not t.table_alias]
            if missing_alias:
                raise ForgeError("table_alias is required for multi-table domains", status_code=400)

        joins = [self._to_plan_join(row) for row in join_rows]
        primary = next((t for t in tables if t.is_primary), tables[0])

        return DomainPlan(
            primary=primary,
            tables=tables,
            joins=joins,
            alias_by_workspace_table_id=alias_map,
            column_name_policy=policy,
        )

    def get_join_path(self, plan: DomainPlan, to_workspace_table_id: int) -> List[DomainPlanJoin]:
        target = int(to_workspace_table_id)
        root = int(plan.primary.workspace_table_id)
        if target == root:
            return []

        edges: Dict[int, List[DomainPlanJoin]] = {}
        for join in plan.joins:
            edges.setdefault(int(join.from_workspace_table_id), []).append(join)

        queue = deque([(root, [])])
        seen = {root}

        while queue:
            current, path = queue.popleft()
            for edge in edges.get(current, []):
                nxt = int(edge.to_workspace_table_id)
                if nxt in seen:
                    continue
                next_path = path + [edge]
                if nxt == target:
                    return next_path
                seen.add(nxt)
                queue.append((nxt, next_path))

        raise ForgeError("Join path not found for table in domain", status_code=400)

    def resolve(self, domain_id: int) -> ResolvedDomainFrom:
        domain_id = self._coerce_domain_id(domain_id)

        mapped_rows = self._sql.execute_query_mappings(
            """
            SELECT wt.id AS workspace_table_id, wt.full_name
            FROM domain_workspace_table dwt
            JOIN workspace_table wt ON wt.id = dwt.workspace_table_id
            WHERE dwt.domain_id = :domain_id
              AND wt.workspace_id = :ws
              AND wt.exists_in_dbx = 1
            ORDER BY wt.id ASC
            """,
            {"domain_id": domain_id, "ws": self._workspace_id},
        )

        if mapped_rows:
            if len(mapped_rows) > 1 and not self._allow_ambiguous:
                raise ForgeError(
                    f"Domain {domain_id} maps to multiple workspace tables in workspace {self._workspace_id}.",
                    status_code=400,
                )
            row = mapped_rows[0]
            return ResolvedDomainFrom(workspace_table_id=int(row["workspace_table_id"]), full_name=_safe_fqn(row["full_name"]))

        raise ForgeError(f"Unknown domainId {domain_id} for workspace {self._workspace_id}", status_code=404)

    def _coerce_domain_id(self, domain_id: int) -> int:
        if not self._workspace_id:
            raise ForgeError("workspace_id is required", status_code=400)
        try:
            return int(domain_id)
        except Exception:
            raise ForgeError("Invalid domainId", status_code=400)

    def _normalize_alias(self, alias: Optional[str]) -> Optional[str]:
        if alias is None:
            return None
        cleaned = alias.strip()
        if not cleaned:
            return None
        if not _IDENT.match(cleaned):
            raise ForgeError(f"Unsafe table alias: {cleaned}", status_code=400)
        return cleaned

    def _normalize_policy(self, value: Any) -> str:
        policy = (str(value or "DEDUP_PRIMARY_FIRST").strip().upper())
        if policy not in _ALLOWED_POLICIES:
            raise ForgeError("Invalid column_name_policy for domain", status_code=400)
        return policy

    def _build_plan_tables(self, table_rows: List[Dict[str, Any]]) -> tuple[List[DomainPlanTable], Dict[int, str]]:
        tables: List[DomainPlanTable] = []
        alias_by_id: Dict[int, str] = {}
        alias_seen: set[str] = set()
        next_alias = 0

        for row in table_rows:
            workspace_table_id = int(row["workspace_table_id"])
            explicit_alias = self._normalize_alias(row.get("table_alias"))
            full_name = _safe_fqn(str(row["full_name"]))

            filter_mode = str(row.get("filter_mode") or "AUTO").strip().upper()
            if filter_mode not in _ALLOWED_FILTER_MODES:
                raise ForgeError(f"Invalid filter_mode for table {workspace_table_id}", status_code=400)

            cardinality = str(row.get("cardinality") or "ONE").strip().upper()
            if cardinality not in _ALLOWED_CARDINALITY:
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

    def _to_plan_join(self, row: Dict[str, Any]) -> DomainPlanJoin:
        raw_spec = row.get("join_spec_json")
        if isinstance(raw_spec, str):
            try:
                parsed_spec = json.loads(raw_spec)
            except Exception:
                raise ForgeError("Invalid join_spec_json", status_code=400)
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
