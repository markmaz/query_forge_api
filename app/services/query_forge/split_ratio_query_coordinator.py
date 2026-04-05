from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from app.services.domain_resolver import DomainPlan
from app.services.query_forge.split_ratio_compiler import SplitRatioCompiler
from app.services.query_forge.types import ForgeCompiledQuery


class QueryForgeSplitRatioCoordinator:
    def __init__(
        self,
        *,
        severity_predicate_for_alias: Callable[..., str],
        qf_safe_ident: Callable[[str], str],
        compile_where: Callable[..., tuple[str, list[str]]],
        from_clause_from_plan: Callable[..., str],
        required_table_ids_from_query: Callable[[Dict[str, Any], DomainPlan], set[int]],
        compile_metric: Callable[..., str],
    ) -> None:
        self._severity_predicate_for_alias = severity_predicate_for_alias
        self._qf_safe_ident = qf_safe_ident
        self._compile_where = compile_where
        self._from_clause_from_plan = from_clause_from_plan
        self._required_table_ids_from_query = required_table_ids_from_query
        self._compile_metric = compile_metric

    def compile(
        self,
        *,
        q: Dict[str, Any],
        plan: DomainPlan,
        split_metric: Dict[str, Any],
        mode: str,
        limit: int,
        offset: int,
        severity_table_ids: Optional[set[int]] = None,
    ) -> ForgeCompiledQuery:
        if severity_table_ids is None:
            severity_table_ids = set()
        primary_id = int(plan.primary.workspace_table_id)
        qf_base_alias = plan.primary.alias
        alias_by_wt = plan.alias_by_workspace_table_id
        primary_severity_pred = self._severity_predicate_for_alias(
            alias=self._qf_safe_ident(qf_base_alias),
            workspace_table_id=primary_id,
            severity_table_ids=severity_table_ids,
        )

        def compile_where_fn(
            filters_node,
            derived_by_exprid,
            derived_by_name,
            rewrite_by_colname,
            rewrite_by_modelid,
            qf_using_prep,
            qf_base_alias_,
            alias_by_wt_,
            new_param_,
            *,
            severity_table_ids=None,
        ):
            return self._compile_where(
                filters_node,
                derived_by_exprid,
                derived_by_name,
                rewrite_by_colname,
                rewrite_by_modelid,
                qf_using_prep,
                qf_base_alias_,
                alias_by_wt_,
                plan,
                new_param_,
                severity_table_ids=severity_table_ids,
            )

        def from_clause_fn(required_table_ids, *, severity_table_ids=None):
            return self._from_clause_from_plan(plan, required_table_ids, severity_table_ids=severity_table_ids)

        def required_table_ids_fn(side_query):
            return self._required_table_ids_from_query(side_query, plan)

        def compile_metric_fn(fn, field, derived_by_exprid, derived_by_name, rewrite_by_colname, rewrite_by_modelid, qf_using_prep, qf_base_alias_, alias_by_wt_):
            return self._compile_metric(
                fn,
                field,
                derived_by_exprid,
                derived_by_name,
                rewrite_by_colname,
                rewrite_by_modelid,
                qf_using_prep,
                qf_base_alias_,
                alias_by_wt_,
            )

        return SplitRatioCompiler().compile(
            query_json=q,
            split_metric=split_metric,
            primary_id=primary_id,
            qf_base_alias=qf_base_alias,
            alias_by_wt=alias_by_wt,
            mode=mode,
            limit=limit,
            offset=offset,
            compile_where_fn=compile_where_fn,
            from_clause_fn=from_clause_fn,
            required_table_ids_fn=required_table_ids_fn,
            compile_metric_fn=compile_metric_fn,
            severity_pred=primary_severity_pred,
            severity_table_ids=severity_table_ids,
        )
