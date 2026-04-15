from __future__ import annotations

import re
from typing import Any, Callable, Dict, List, Optional

from app.exceptions.forge_error import ForgeError
from app.services.domain_resolver import DomainPlan


class QueryForgeJoinCompiler:
    def __init__(
        self,
        *,
        qf_safe_ident: Callable[[str], str],
    ) -> None:
        self._qf_safe_ident = qf_safe_ident

    def compile_from_plan(
        self,
        plan: DomainPlan,
        required_table_ids: set[int],
        *,
        get_join_path: Callable[[DomainPlan, int], List[Any]],
        severity_predicate_for_alias: Callable[..., str],
        severity_table_ids: Optional[set[int]] = None,
    ) -> str:
        if severity_table_ids is None:
            severity_table_ids = set()
        tables_by_id = {t.workspace_table_id: t for t in plan.tables}
        needed_edges: Dict[tuple[str, int, int], Any] = {}
        for wt_id in required_table_ids:
            if int(wt_id) == int(plan.primary.workspace_table_id):
                continue
            for edge in get_join_path(plan, int(wt_id)):
                needed_edges[(str(edge.join_id), int(edge.from_workspace_table_id), int(edge.to_workspace_table_id))] = edge

        joined = {plan.primary.workspace_table_id}
        clauses = [f"{plan.primary.full_name} {self._qf_safe_ident(plan.primary.alias)}"]
        remaining_edges = sorted(
            needed_edges.values(),
            key=lambda edge: (int(getattr(edge, "sort_order", 0)), str(edge.join_id)),
        )
        while remaining_edges:
            progress = False
            deferred: List[Any] = []
            for edge in remaining_edges:
                if edge.from_workspace_table_id == edge.to_workspace_table_id:
                    raise ForgeError("Join cannot reference the same table", status_code=400)
                if edge.from_workspace_table_id not in tables_by_id or edge.to_workspace_table_id not in tables_by_id:
                    raise ForgeError("Join references table not in domain", status_code=400)
                if edge.from_workspace_table_id not in joined:
                    deferred.append(edge)
                    continue

                join_type = (edge.join_type or "").upper()
                if join_type not in {"INNER", "LEFT", "RIGHT"}:
                    raise ForgeError(f"Invalid join_type: {join_type}", status_code=400)

                to_table = tables_by_id[edge.to_workspace_table_id]
                on_sql = self.compile_join_on(edge, plan.alias_by_workspace_table_id)
                severity_pred = severity_predicate_for_alias(
                    alias=self._qf_safe_ident(to_table.alias),
                    workspace_table_id=int(to_table.workspace_table_id),
                    severity_table_ids=severity_table_ids,
                )
                if severity_pred:
                    on_sql = f"{on_sql} AND {severity_pred}"
                clauses.append(
                    f"{join_type} JOIN {to_table.full_name} {self._qf_safe_ident(to_table.alias)} ON {on_sql}"
                )
                joined.add(edge.to_workspace_table_id)
                progress = True

            if progress:
                remaining_edges = deferred
                continue

            raise ForgeError("Join order invalid: from table not yet joined", status_code=400)

        missing = [
            t.workspace_table_id
            for t in plan.tables
            if t.workspace_table_id in required_table_ids and t.workspace_table_id not in joined
        ]
        if missing:
            raise ForgeError("Domain join plan does not cover all tables", status_code=400)

        return "\n".join(clauses)

    def compile_join_on(self, edge: Any, alias_by_wt: Dict[int, str]) -> str:
        from_alias = alias_by_wt.get(int(edge.from_workspace_table_id))
        to_alias = alias_by_wt.get(int(edge.to_workspace_table_id))
        if not from_alias or not to_alias:
            raise ForgeError("Join references table not in domain", status_code=400)

        return " AND ".join(self.join_predicates(edge, from_alias, to_alias))

    def join_predicates(self, edge: Any, from_alias: str, to_alias: str) -> List[str]:
        spec = edge.join_spec or {}
        on_list = spec.get("on") or []
        if not isinstance(on_list, list) or not on_list:
            raise ForgeError("Join spec must include non-empty on[]", status_code=400)

        preds = []
        for item in on_list:
            if not isinstance(item, dict):
                raise ForgeError("Join spec on[] must be objects", status_code=400)

            left = item.get("left") or {}
            right = item.get("right") or {}

            left_wt = left.get("workspaceTableId")
            right_wt = right.get("workspaceTableId")
            if left_wt is not None and int(left_wt) != int(edge.from_workspace_table_id):
                raise ForgeError("Join spec left.workspaceTableId must match from table", status_code=400)
            if right_wt is not None and int(right_wt) != int(edge.to_workspace_table_id):
                raise ForgeError("Join spec right.workspaceTableId must match to table", status_code=400)

            left_expr = self.compile_join_side(left, expected_scope="from", alias=from_alias)
            right_expr = self.compile_join_side(right, expected_scope="to", alias=to_alias)

            preds.append(f"{left_expr} = {right_expr}")

        return preds

    def compile_join_side(self, side: Dict[str, Any], *, expected_scope: str, alias: str) -> str:
        expr = side.get("expr")
        if expr:
            scope, col, key = self.parse_join_expr(expr)
            if scope != expected_scope:
                raise ForgeError("Join spec expr uses wrong table scope", status_code=400)
            return f"get_json_object({self._qf_safe_ident(alias)}.{self._qf_safe_ident(col)}, '$.{key}')"

        col = side.get("columnName") or side.get("col")
        if not col or not isinstance(col, str) or "." in col:
            raise ForgeError("Join spec column invalid", status_code=400)
        return f"{self._qf_safe_ident(alias)}.{self._qf_safe_ident(col)}"

    @staticmethod
    def parse_join_expr(expr: str) -> tuple[str, str, str]:
        pattern = r"^get_json_object\(\{(from|to)\}\.([A-Za-z0-9_]+),\s*'\$\.([A-Za-z0-9_]+)'\)$"
        match = re.match(pattern, expr)
        if not match:
            raise ForgeError(
                "Join spec expr must match get_json_object({from|to}.<col>, '$.<key>')",
                status_code=400,
            )
        return match.group(1), match.group(2), match.group(3)
