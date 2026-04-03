from __future__ import annotations

from typing import List, Optional

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.services.domain_resolution.join_path_service import DomainJoinPathService
from app.services.domain_resolution.models import (
    DomainPlan,
    DomainPlanJoin,
    DomainPlanTable,
    ResolvedDomainFrom,
    safe_fqn,
)
from app.services.domain_resolution.plan_builder import build_plan_tables, normalize_policy, to_plan_join
from app.services.domain_resolution.query_service import DomainResolutionQueryService
from app.exceptions.forge_error import ForgeError
from app.ports.sql_executor import ForgeQueryPort

__all__ = [
    "ResolvedDomainFrom",
    "DomainPlanTable",
    "DomainPlanJoin",
    "DomainPlan",
    "DomainResolver",
    "_safe_fqn",
]

def _safe_fqn(full_name: str) -> str:
    return safe_fqn(full_name)


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
        self._queries = DomainResolutionQueryService(sql=self._sql, workspace_id=self._workspace_id)
        self._join_paths = DomainJoinPathService()

    def resolve_plan(self, domain_id: int) -> DomainPlan:
        domain_id = self._coerce_domain_id(domain_id)
        table_rows, join_rows = self._queries.fetch_plan_rows(domain_id=domain_id)

        if not table_rows:
            raise ForgeError(f"Unknown domainId {domain_id} for workspace {self._workspace_id}", status_code=404)

        policy = normalize_policy(table_rows[0].get("column_name_policy"))
        tables, alias_map = build_plan_tables(table_rows)

        if len(tables) > 1 and policy == "SHOW_ALL_QUALIFIED":
            missing_alias = [t.workspace_table_id for t in tables if not t.table_alias]
            if missing_alias:
                raise ForgeError("table_alias is required for multi-table domains", status_code=400)

        joins = [to_plan_join(row) for row in join_rows]
        primary = next((t for t in tables if t.is_primary), tables[0])

        return DomainPlan(
            primary=primary,
            tables=tables,
            joins=joins,
            alias_by_workspace_table_id=alias_map,
            column_name_policy=policy,
        )

    def get_join_path(self, plan: DomainPlan, to_workspace_table_id: int) -> List[DomainPlanJoin]:
        return self._join_paths.get_join_path(plan, to_workspace_table_id)

    def resolve(self, domain_id: int) -> ResolvedDomainFrom:
        domain_id = self._coerce_domain_id(domain_id)

        mapped_rows = self._queries.fetch_mapped_rows(domain_id=domain_id)

        if mapped_rows:
            if len(mapped_rows) > 1 and not self._allow_ambiguous:
                raise ForgeError(
                    f"Domain {domain_id} maps to multiple workspace tables in workspace {self._workspace_id}.",
                    status_code=400,
                )
            row = mapped_rows[0]
            return ResolvedDomainFrom(
                workspace_table_id=int(row["workspace_table_id"]),
                full_name=_safe_fqn(row["full_name"]),
            )

        raise ForgeError(f"Unknown domainId {domain_id} for workspace {self._workspace_id}", status_code=404)

    def _coerce_domain_id(self, domain_id: int) -> int:
        if not self._workspace_id:
            raise ForgeError("workspace_id is required", status_code=400)
        try:
            return int(domain_id)
        except Exception:
            raise ForgeError("Invalid domainId", status_code=400)
