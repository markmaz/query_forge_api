from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from app.exceptions.forge_error import ForgeError
from app.services.domain_resolver import DomainPlan
from app.services.query_forge.projection_compiler import QueryForgeProjectionResult
from app.services.query_forge.types import ForgeCompiledQuery


class QueryForgeStandardCompiler:
    def __init__(
        self,
        *,
        build_context: Callable[..., Any],
        filter_table_ids: Callable[[Any, DomainPlan], set[int]],
        sorting_table_ids: Callable[[Any, DomainPlan], set[int]],
        compile_projection: Callable[..., QueryForgeProjectionResult],
        merge_attachment_selects: Callable[..., QueryForgeProjectionResult],
        select_two_phase_key_column: Callable[..., Optional[str]],
        compile_where: Callable[..., tuple[str, list[str]]],
        compile_order_by: Callable[..., str],
        assemble_sql: Callable[..., Any],
    ) -> None:
        self._build_context = build_context
        self._filter_table_ids = filter_table_ids
        self._sorting_table_ids = sorting_table_ids
        self._compile_projection = compile_projection
        self._merge_attachment_selects = merge_attachment_selects
        self._select_two_phase_key_column = select_two_phase_key_column
        self._compile_where = compile_where
        self._compile_order_by = compile_order_by
        self._assemble_sql = assemble_sql

    def compile(
        self,
        *,
        q: Dict[str, Any],
        plan: DomainPlan,
        mode: str,
        limit: int,
        offset: int,
        severity_table_ids: set[int],
    ) -> ForgeCompiledQuery:
        compile_ctx = self._build_context(
            q=q,
            plan=plan,
            severity_table_ids=severity_table_ids,
        )
        primary_id = compile_ctx.primary_id
        qf_base_alias = compile_ctx.qf_base_alias
        alias_by_wt = compile_ctx.alias_by_wt
        projected_table_ids = compile_ctx.projected_table_ids
        filter_only_table_ids = compile_ctx.filter_only_table_ids
        attachment_required_table_ids = compile_ctx.attachment_required_table_ids
        from_clause_sql = compile_ctx.from_clause_sql
        qf_cte_sql = compile_ctx.qf_cte_sql
        derived_by_exprid = compile_ctx.derived_by_exprid
        derived_by_name = compile_ctx.derived_by_name
        rewrite_by_colname = compile_ctx.rewrite_by_colname
        rewrite_by_modelid = compile_ctx.rewrite_by_modelid
        rewrite_by_wt_col = compile_ctx.rewrite_by_wt_col
        qf_using_prep = compile_ctx.qf_using_prep
        primary_severity_pred = compile_ctx.primary_severity_pred
        qf_attach_ctx = compile_ctx.qf_attach_ctx
        params = compile_ctx.params
        new_param = compile_ctx.new_param

        filters = q.get("filters")
        filter_table_ids = self._filter_table_ids(filters, plan)
        sorting_table_ids = self._sorting_table_ids(q.get("sorting") or [], plan)

        aggs = q.get("aggs") or {"enabled": False}
        distinct = bool(q.get("distinct", False))
        projection = self._compile_projection(
            raw_cols=q.get("columns") or [],
            aggs=aggs,
            distinct=distinct,
            plan=plan,
            derived_by_exprid=derived_by_exprid,
            derived_by_name=derived_by_name,
            rewrite_by_colname=rewrite_by_colname,
            rewrite_by_modelid=rewrite_by_modelid,
            rewrite_by_wt_col=rewrite_by_wt_col,
            qf_using_prep=qf_using_prep,
            qf_base_alias=qf_base_alias,
            alias_by_wt=alias_by_wt,
        )
        select_exprs = list(projection.select_exprs)
        group_by_exprs = projection.group_by_exprs
        qf_output_cols = list(projection.qf_output_cols)
        order_alias_by_key = projection.order_alias_by_key
        metric_alias_by_ref = projection.metric_alias_by_ref

        if not select_exprs:
            raise ForgeError("No selectable columns/expressions produced.", status_code=400)

        projected_non_primary = projected_table_ids - {primary_id}
        use_two_phase = (
            mode == "preview"
            and bool(filter_only_table_ids)
            and not bool((aggs or {}).get("enabled"))
            and not qf_using_prep
            and not (filter_table_ids & projected_non_primary)
            and sorting_table_ids.issubset({primary_id})
        )
        two_phase_key_col: Optional[str] = None
        if use_two_phase:
            two_phase_key_col = self._select_two_phase_key_column(
                q=q,
                plan=plan,
                primary_id=primary_id,
                filter_only_table_ids=filter_only_table_ids,
            )
            if not two_phase_key_col:
                use_two_phase = False

        where_sql, exists_parts = self._compile_where(
            filters,
            derived_by_exprid,
            derived_by_name,
            rewrite_by_colname,
            rewrite_by_modelid,
            qf_using_prep,
            qf_base_alias,
            alias_by_wt,
            plan,
            new_param,
            rewrite_by_wt_col=rewrite_by_wt_col,
            force_exists_for_tables=filter_only_table_ids if use_two_phase else None,
            severity_table_ids=severity_table_ids,
        )
        projection = self._merge_attachment_selects(
            projection,
            qf_attach_ctx["selects"],
            aggs_enabled=bool(aggs and aggs.get("enabled")),
        )
        select_exprs = list(projection.select_exprs)
        qf_output_cols = list(projection.qf_output_cols)

        order_sql = self._compile_order_by(
            q.get("sorting") or [],
            derived_by_exprid,
            derived_by_name,
            rewrite_by_colname,
            rewrite_by_modelid,
            qf_using_prep,
            qf_base_alias,
            alias_by_wt,
            rewrite_by_wt_col=rewrite_by_wt_col,
            order_alias_by_key=order_alias_by_key,
            metric_alias_by_ref=metric_alias_by_ref,
            distinct=distinct,
        )
        assembled = self._assemble_sql(
            plan=plan,
            primary_id=primary_id,
            qf_base_alias=qf_base_alias,
            from_clause_sql=from_clause_sql,
            qf_cte_sql=qf_cte_sql,
            qf_using_prep=qf_using_prep,
            primary_severity_pred=primary_severity_pred,
            severity_table_ids=severity_table_ids,
            select_exprs=select_exprs,
            group_by_exprs=group_by_exprs,
            distinct=distinct,
            order_sql=order_sql,
            where_sql=where_sql,
            exists_parts=exists_parts,
            attachment_required_table_ids=attachment_required_table_ids,
            projected_table_ids=projected_table_ids,
            qf_attach_ctx=qf_attach_ctx,
            use_two_phase=use_two_phase,
            two_phase_key_col=two_phase_key_col,
            mode=mode,
            limit=limit,
            offset=offset,
        )

        return ForgeCompiledQuery(
            sql=assembled.sql,
            qf_count_sql=assembled.qf_count_sql,
            params=params,
            qf_output_cols=qf_output_cols,
        )
