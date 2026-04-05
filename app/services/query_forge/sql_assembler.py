from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional, Sequence

from app.services.domain_resolver import DomainPlan


@dataclass(frozen=True)
class QueryForgeAssembledSql:
    sql: str
    qf_count_sql: str


class QueryForgeSqlAssembler:
    def __init__(
        self,
        *,
        qf_safe_ident: Callable[[str], str],
        from_clause_from_plan: Callable[..., str],
    ) -> None:
        self._qf_safe_ident = qf_safe_ident
        self._from_clause_from_plan = from_clause_from_plan

    def assemble(
        self,
        *,
        plan: DomainPlan,
        primary_id: int,
        qf_base_alias: str,
        from_clause_sql: str,
        qf_cte_sql: str,
        qf_using_prep: bool,
        primary_severity_pred: str,
        severity_table_ids: set[int],
        select_exprs: Sequence[str],
        group_by_exprs: Sequence[str],
        distinct: bool,
        order_sql: str,
        where_sql: str,
        exists_parts: Sequence[str],
        attachment_required_table_ids: set[int],
        projected_table_ids: set[int],
        qf_attach_ctx: Dict[str, Any],
        use_two_phase: bool,
        two_phase_key_col: Optional[str],
        mode: str,
        limit: int,
        offset: int,
    ) -> QueryForgeAssembledSql:
        working_from_clause_sql = from_clause_sql
        if qf_using_prep and qf_attach_ctx["needs_base_alias"] and working_from_clause_sql.strip() == "prep":
            working_from_clause_sql = f"{working_from_clause_sql} {self._qf_safe_ident(qf_base_alias)}"

        if qf_attach_ctx["joins"]:
            working_from_clause_sql = f"{working_from_clause_sql}\n" + "\n".join(qf_attach_ctx["joins"])

        select_prefix = "SELECT DISTINCT" if distinct else "SELECT"
        base_where_parts = [
            part
            for part in ([where_sql] if where_sql else []) + list(exists_parts or []) + qf_attach_ctx["where"]
            if part
        ]
        if (not qf_using_prep) and primary_severity_pred:
            base_where_parts.insert(0, primary_severity_pred)

        base_patients_cte = ""
        base_patients_cte_count = ""
        if use_two_phase:
            two_phase_key_col_sql = self._qf_safe_ident(str(two_phase_key_col or "patient_id"))
            base_patients_cte = self._render_base_patients_cte(
                qf_base_alias=qf_base_alias,
                plan=plan,
                two_phase_key_col_sql=two_phase_key_col_sql,
                base_where_parts=base_where_parts,
            )
            base_patients_cte_count = base_patients_cte

            projection_table_ids = (projected_table_ids | attachment_required_table_ids | {primary_id}) - {0}
            projection_from_sql = self._from_clause_from_plan(
                plan,
                projection_table_ids,
                severity_table_ids=severity_table_ids,
            )
            projection_lines = projection_from_sql.split("\n")
            join_lines = projection_lines[1:] if len(projection_lines) > 1 else []
            primary_join_parts = [f"{self._qf_safe_ident(qf_base_alias)}.{two_phase_key_col_sql} = bp.{two_phase_key_col_sql}"]
            if primary_severity_pred:
                primary_join_parts.append(primary_severity_pred)
            working_from_clause_sql = (
                f"base_patients bp\n"
                f"JOIN {plan.primary.full_name} {self._qf_safe_ident(qf_base_alias)} "
                f"ON {' AND '.join(primary_join_parts)}"
            )
            if join_lines:
                working_from_clause_sql += "\n" + "\n".join(join_lines)
            if qf_attach_ctx["joins"]:
                working_from_clause_sql = f"{working_from_clause_sql}\n" + "\n".join(qf_attach_ctx["joins"])

        base_sql = f"{select_prefix} {', '.join(select_exprs)}\nFROM {working_from_clause_sql}"
        if not use_two_phase and base_where_parts:
            base_sql += f"\nWHERE {' AND '.join(base_where_parts)}"
        if group_by_exprs:
            base_sql += f"\nGROUP BY {', '.join(group_by_exprs)}"

        base_cte_sql = qf_cte_sql
        final_cte_sql = self._append_ctes(qf_cte_sql, [base_patients_cte] if base_patients_cte else [], qf_attach_ctx["ctes"])
        if final_cte_sql:
            base_sql = f"{final_cte_sql}\n{base_sql}"

        if use_two_phase:
            cte_sql_count = self._append_ctes(base_cte_sql, [base_patients_cte_count] if base_patients_cte_count else [], qf_attach_ctx["ctes"])
            base_sql_count = f"{select_prefix} {', '.join(select_exprs)}\nFROM {working_from_clause_sql}"
            if group_by_exprs:
                base_sql_count += f"\nGROUP BY {', '.join(group_by_exprs)}"
            if cte_sql_count:
                base_sql_count = f"{cte_sql_count}\n{base_sql_count}"
            qf_count_sql = f"SELECT COUNT(*) AS total FROM (\n{base_sql_count}\n) q"
        else:
            qf_count_sql = f"SELECT COUNT(*) AS total FROM (\n{base_sql}\n) q"

        sql = base_sql
        if order_sql:
            sql += f"\nORDER BY {order_sql}"
        if mode == "preview":
            sql += f"\nLIMIT {int(limit)}\nOFFSET {int(offset)}"

        return QueryForgeAssembledSql(sql=sql, qf_count_sql=qf_count_sql)

    def _render_base_patients_cte(
        self,
        *,
        qf_base_alias: str,
        plan: DomainPlan,
        two_phase_key_col_sql: str,
        base_where_parts: Sequence[str],
    ) -> str:
        return (
            "base_patients AS (\n"
            f"  SELECT DISTINCT {self._qf_safe_ident(qf_base_alias)}.{two_phase_key_col_sql}\n"
            f"  FROM {plan.primary.full_name} {self._qf_safe_ident(qf_base_alias)}\n"
            + (f"  WHERE {' AND '.join(base_where_parts)}\n" if base_where_parts else "")
            + ")"
        )

    @staticmethod
    def _append_ctes(
        current_cte_sql: str,
        extra_ctes: Sequence[str],
        attachment_ctes: Sequence[str],
    ) -> str:
        ctes = [cte for cte in extra_ctes if cte]
        if attachment_ctes:
            ctes.extend(attachment_ctes)
        if not ctes:
            return current_cte_sql
        if current_cte_sql:
            return f"{current_cte_sql},\n" + ",\n".join(ctes)
        return "WITH " + ",\n".join(ctes)
