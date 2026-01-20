from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Dict, List, Optional

from app.adapters.mysql_sql_executor import MySQLSQLExecutor
from app.exceptions.service_error import ServiceError
from app.ports.sql_executor import SQLExecutor

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _safe_fqn(full_name: str) -> str:
    """
    Accept only catalog.schema.table (3-part) OR schema.table (2-part).
    Reject anything with spaces, quotes, semicolons, etc.
    """
    if not full_name or not isinstance(full_name, str):
        raise ServiceError("Invalid resolved table name", status_code=400)

    parts = full_name.split(".")
    if len(parts) not in (2, 3):
        raise ServiceError(f"Invalid table full_name: {full_name}", status_code=400)

    for p in parts:
        if not _IDENT.match(p):
            raise ServiceError(f"Unsafe identifier in full_name: {full_name}", status_code=400)

    return full_name


@dataclass(frozen=True)
class ResolvedDomainFrom:
    workspace_table_id: int
    full_name: str  # safe FQN


@dataclass(frozen=True)
class DomainPlanTable:
    workspace_table_id: int
    full_name: str  # safe FQN
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
    Resolve (workspace_id, domain_id) -> a workspace_table target.

    Uses:
      1) domain_workspace_table mapping
      2) fallback: domain.model_table_id -> workspace_table.model_table_id

    Strict by default: if mapping yields multiple tables, error.
    """

    def __init__(self, *, workspace_id: str, allow_ambiguous: bool = False, sql: Optional[SQLExecutor] = None):
        self._allow_ambiguous = allow_ambiguous
        self._workspace_id = workspace_id
        self._sql = sql or MySQLSQLExecutor()

    def resolve_plan(self, domain_id: int) -> DomainPlan:
        if not self._workspace_id:
            raise ServiceError("workspace_id is required", status_code=400)

        try:
            domain_id = int(domain_id)
        except Exception:
            raise ServiceError("Invalid domainId", status_code=400)

        tables_sql = """
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
            """

        joins_sql = """
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
            """

        table_rows = self._sql.execute_query_mappings(
            tables_sql, {"did": domain_id, "ws": self._workspace_id}
        )
        join_rows = self._sql.execute_query_mappings(joins_sql, {"did": domain_id})

        if not table_rows:
            raise ServiceError(f"Unknown domainId {domain_id} for workspace {self._workspace_id}", status_code=404)

        def safe_alias(v: Optional[str]) -> Optional[str]:
            if v is None:
                return None
            v = v.strip()
            if not v:
                return None
            if not _IDENT.match(v):
                raise ServiceError(f"Unsafe table alias: {v}", status_code=400)
            return v

        # build tables + aliases (primary first)
        used_aliases: Dict[str, int] = {}
        tables: List[DomainPlanTable] = []
        next_idx = 0

        column_name_policy = (table_rows[0].get("column_name_policy") or "DEDUP_PRIMARY_FIRST").strip().upper()
        if column_name_policy not in {"DEDUP_PRIMARY_FIRST", "SHOW_ALL_QUALIFIED"}:
            raise ServiceError("Invalid column_name_policy for domain", status_code=400)

        for row in table_rows:
            wt_id = int(row["workspace_table_id"])
            full_name = _safe_fqn(row["full_name"])
            table_alias = safe_alias(row.get("table_alias"))
            is_primary = bool(row.get("is_primary"))
            sort_order = int(row.get("sort_order") or 0)
            filter_mode = (row.get("filter_mode") or "AUTO").strip().upper()
            if filter_mode not in {"WHERE", "EXISTS", "AUTO"}:
                raise ServiceError(f"Invalid filter_mode for table {wt_id}", status_code=400)
            cardinality = (row.get("cardinality") or "ONE").strip().upper()
            if cardinality not in {"ONE", "MANY"}:
                raise ServiceError(f"Invalid cardinality for table {wt_id}", status_code=400)

            alias = table_alias
            if alias and alias in used_aliases:
                alias = None

            if not alias:
                while True:
                    candidate = f"t{next_idx}"
                    next_idx += 1
                    if candidate not in used_aliases:
                        alias = candidate
                        break

            used_aliases[str(alias)] = wt_id
            tables.append(
                DomainPlanTable(
                    workspace_table_id=wt_id,
                    full_name=full_name,
                    alias=str(alias),
                    table_alias=table_alias,
                    is_primary=is_primary,
                    sort_order=sort_order,
                    filter_mode=filter_mode,
                    cardinality=cardinality,
                )
            )

        primary = None
        for t in tables:
            if t.is_primary:
                primary = t
                break
        if primary is None:
            primary = tables[0]

        alias_by_wt = {t.workspace_table_id: t.alias for t in tables}

        if len(tables) > 1 and column_name_policy == "SHOW_ALL_QUALIFIED":
            missing_alias = [t.workspace_table_id for t in tables if not t.table_alias]
            if missing_alias:
                raise ServiceError("table_alias is required for multi-table domains", status_code=400)

        joins: List[DomainPlanJoin] = []
        for jr in join_rows:
            join_spec_raw = jr.get("join_spec_json")
            if isinstance(join_spec_raw, str):
                try:
                    join_spec = json.loads(join_spec_raw)
                except Exception:
                    raise ServiceError("Invalid join_spec_json", status_code=400)
            elif isinstance(join_spec_raw, dict):
                join_spec = join_spec_raw
            else:
                join_spec = {}

            joins.append(
                DomainPlanJoin(
                    join_id=str(jr.get("id")),
                    from_workspace_table_id=int(jr["from_workspace_table_id"]),
                    to_workspace_table_id=int(jr["to_workspace_table_id"]),
                    join_type=str(jr.get("join_type") or "").upper(),
                    join_spec=join_spec if isinstance(join_spec, dict) else {},
                    sort_order=int(jr.get("sort_order") or 0),
                )
            )

        return DomainPlan(
            primary=primary,
            tables=tables,
            joins=joins,
            alias_by_workspace_table_id=alias_by_wt,
            column_name_policy=column_name_policy,
        )

    def get_join_path(self, plan: DomainPlan, to_workspace_table_id: int) -> List[DomainPlanJoin]:
        if int(to_workspace_table_id) == int(plan.primary.workspace_table_id):
            return []

        edges_by_from: Dict[int, List[DomainPlanJoin]] = {}
        for e in plan.joins:
            edges_by_from.setdefault(int(e.from_workspace_table_id), []).append(e)

        queue = [(int(plan.primary.workspace_table_id), [])]
        visited = {int(plan.primary.workspace_table_id)}

        while queue:
            current, path = queue.pop(0)
            for e in edges_by_from.get(int(current), []):
                nxt = int(e.to_workspace_table_id)
                if nxt in visited:
                    continue
                new_path = path + [e]
                if nxt == int(to_workspace_table_id):
                    return new_path
                visited.add(nxt)
                queue.append((nxt, new_path))

        raise ServiceError("Join path not found for table in domain", status_code=400)

    def resolve(self, domain_id: int) -> ResolvedDomainFrom:
        if not self._workspace_id:
            raise ServiceError("workspace_id is required", status_code=400)

        try:
            domain_id = int(domain_id)
        except Exception:
            raise ServiceError("Invalid domainId", status_code=400)

        # 1) Explicit mapping
        rows = self._sql.execute_query_mappings(
            """
            SELECT wt.id AS workspace_table_id, wt.full_name
            FROM domain_workspace_table dwt
            JOIN workspace_table wt
              ON wt.id = dwt.workspace_table_id
            WHERE dwt.domain_id = :domain_id
              AND wt.workspace_id = :ws
              AND wt.exists_in_dbx = 1
            ORDER BY wt.id ASC
            """,
            {"domain_id": domain_id, "ws": self._workspace_id},
        )

        if rows:
            if len(rows) > 1 and not self._allow_ambiguous:
                raise ServiceError(
                    f"Domain {domain_id} maps to multiple workspace tables in workspace {self._workspace_id}.",
                    status_code=400,
                )

            wt_id = int(rows[0]["workspace_table_id"])
            full_name = _safe_fqn(rows[0]["full_name"])
            return ResolvedDomainFrom(workspace_table_id=wt_id, full_name=full_name)

        # 2) Fallback via model_table_id (if you still want this behavior)
        fallback_rows = self._sql.execute_query_mappings(
            """
            SELECT wt.id AS workspace_table_id, wt.full_name
            FROM domain d
            JOIN workspace_table wt
              ON wt.model_table_id = d.model_table_id
             AND wt.workspace_id = d.workspace_id
            WHERE d.id = :domain_id
              AND d.workspace_id = :ws
              AND d.is_active = 1
              AND wt.exists_in_dbx = 1
            ORDER BY wt.id ASC
            LIMIT 1
            """,
            {"domain_id": domain_id, "ws": self._workspace_id},
        )
        row = fallback_rows[0] if fallback_rows else None

        if row:
            wt_id = int(row["workspace_table_id"])
            full_name = _safe_fqn(row["full_name"])
            return ResolvedDomainFrom(workspace_table_id=wt_id, full_name=full_name)

        raise ServiceError(f"Unknown domainId {domain_id} for workspace {self._workspace_id}", status_code=404)
