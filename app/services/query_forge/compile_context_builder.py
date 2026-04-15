from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from app.services.domain_resolver import DomainPlan


@dataclass
class QueryForgeStandardCompileContext:
    primary_id: int
    qf_base_alias: str
    alias_by_wt: Dict[int, str]
    value_override_attachments: List[Any]
    cohort_attachment: Optional[Dict[str, Any]]
    projected_table_ids: set[int]
    filter_only_table_ids: set[int]
    attachment_required_table_ids: set[int]
    from_clause_sql: str
    qf_cte_sql: str
    derived_by_exprid: Dict[str, str]
    derived_by_name: Dict[str, str]
    rewrite_by_colname: Dict[str, str]
    rewrite_by_modelid: Dict[int, str]
    rewrite_by_wt_col: Dict[tuple, str]
    qf_using_prep: bool
    primary_severity_pred: str
    qf_attach_ctx: Dict[str, Any]
    params: Dict[str, Any]
    new_param: Callable[[Any], str]


class QueryForgeCompileContextBuilder:
    def __init__(
        self,
        *,
        required_table_ids_from_query: Callable[[Dict[str, Any], DomainPlan], set[int]],
        attach_table_ids: Callable[[List[Any], Optional[Dict[str, Any]], int], set[int]],
        from_clause_from_plan: Callable[..., str],
        compile_data_prep_meta: Callable[[Any, str, Dict[int, str]], Dict[str, Any]],
        severity_predicate_for_alias: Callable[..., str],
        collect_required_column_keys: Callable[..., List[Dict[str, Any]]],
        build_prep_base_selects: Callable[..., tuple[List[str], Dict[str, str], Dict[int, str], Dict[tuple, str]]],
        render_data_prep_cte: Callable[..., str],
        compile_attachments: Callable[..., Dict[str, Any]],
        qf_safe_ident: Callable[[str], str],
    ) -> None:
        self._required_table_ids_from_query = required_table_ids_from_query
        self._attach_table_ids = attach_table_ids
        self._from_clause_from_plan = from_clause_from_plan
        self._compile_data_prep_meta = compile_data_prep_meta
        self._severity_predicate_for_alias = severity_predicate_for_alias
        self._collect_required_column_keys = collect_required_column_keys
        self._build_prep_base_selects = build_prep_base_selects
        self._render_data_prep_cte = render_data_prep_cte
        self._compile_attachments = compile_attachments
        self._qf_safe_ident = qf_safe_ident

    def build(
        self,
        *,
        q: Dict[str, Any],
        plan: DomainPlan,
        severity_table_ids: set[int],
    ) -> QueryForgeStandardCompileContext:
        primary_id = int(plan.primary.workspace_table_id)
        qf_base_alias = plan.primary.alias
        alias_by_wt = plan.alias_by_workspace_table_id
        value_override_attachments = q.get("value_overrideAttachments") or []
        cohort_attachment = q.get("cohortAttachment")
        base_required_table_ids = self._required_table_ids_from_query(q, plan)
        q_no_filters = dict(q)
        q_no_filters["filters"] = None
        projected_table_ids = self._required_table_ids_from_query(q_no_filters, plan)
        filter_only_table_ids = (base_required_table_ids - projected_table_ids) - {primary_id}
        attachment_required_table_ids = self._attach_table_ids(
            value_override_attachments,
            cohort_attachment,
            primary_id,
        )
        required_table_ids = base_required_table_ids | attachment_required_table_ids
        required_table_ids.discard(0)
        base_from_sql = self._from_clause_from_plan(
            plan,
            required_table_ids,
            severity_table_ids=severity_table_ids,
        )

        dp_meta = self._compile_data_prep_meta(
            q.get("dataPrep"),
            qf_base_alias=qf_base_alias,
            alias_by_wt=alias_by_wt,
        )

        derived_by_exprid = {
            **dp_meta.get("derived_by_exprid", {}),
            **dp_meta.get("computed_alias_by_expr_id", {}),
        }
        derived_by_name = dp_meta["derived_by_name"]
        rewrite_by_colname = dp_meta["rewrite_by_colname"]
        rewrite_by_modelid = dp_meta["rewrite_by_modelid"]
        rewrite_by_wt_col: Dict[tuple, str] = {}
        qf_using_prep = bool(dp_meta["exprs"])
        primary_severity_pred = self._severity_predicate_for_alias(
            alias=self._qf_safe_ident(qf_base_alias),
            workspace_table_id=primary_id,
            severity_table_ids=severity_table_ids,
        )

        required_cols = self._collect_required_column_keys(
            q,
            plan,
            required_table_ids=required_table_ids,
            derived_by_exprid=derived_by_exprid,
            derived_by_name=derived_by_name,
        )
        if qf_using_prep:
            (
                base_selects,
                base_by_colname,
                base_by_modelid,
                base_by_wt_col,
            ) = self._build_prep_base_selects(
                required_cols,
                primary_id=primary_id,
                qf_base_alias=qf_base_alias,
                alias_by_wt=alias_by_wt,
            )

            for key, value in base_by_modelid.items():
                rewrite_by_modelid.setdefault(key, value)
            for key, value in base_by_wt_col.items():
                rewrite_by_wt_col.setdefault(key, value)
            for key, value in base_by_colname.items():
                rewrite_by_colname.setdefault(key, value)

            qf_cte_sql = self._render_data_prep_cte(
                base_from_sql=base_from_sql,
                base_selects=base_selects,
                exprs=dp_meta["exprs"],
                base_where_sql=primary_severity_pred,
            )
            from_clause_sql = "prep"
        else:
            qf_cte_sql = ""
            from_clause_sql = base_from_sql

        params: Dict[str, Any] = {}
        param_counter = 0

        def new_param(val: Any) -> str:
            nonlocal param_counter
            param_counter += 1
            key = f"p{param_counter}"
            params[key] = val
            return f":{key}"

        qf_attach_ctx = self._compile_attachments(
            value_override_attachments=value_override_attachments,
            cohort_attachment=cohort_attachment,
            derived_by_exprid=derived_by_exprid,
            derived_by_name=derived_by_name,
            rewrite_by_colname=rewrite_by_colname,
            rewrite_by_modelid=rewrite_by_modelid,
            rewrite_by_wt_col=rewrite_by_wt_col,
            qf_using_prep=qf_using_prep,
            qf_base_alias=qf_base_alias,
            alias_by_wt=alias_by_wt,
            plan=plan,
            new_param=new_param,
        )

        derived_by_exprid = {**derived_by_exprid, **qf_attach_ctx.get("exprid_sql", {})}

        return QueryForgeStandardCompileContext(
            primary_id=primary_id,
            qf_base_alias=qf_base_alias,
            alias_by_wt=alias_by_wt,
            value_override_attachments=value_override_attachments,
            cohort_attachment=cohort_attachment,
            projected_table_ids=projected_table_ids,
            filter_only_table_ids=filter_only_table_ids,
            attachment_required_table_ids=attachment_required_table_ids,
            from_clause_sql=from_clause_sql,
            qf_cte_sql=qf_cte_sql,
            derived_by_exprid=derived_by_exprid,
            derived_by_name=derived_by_name,
            rewrite_by_colname=rewrite_by_colname,
            rewrite_by_modelid=rewrite_by_modelid,
            rewrite_by_wt_col=rewrite_by_wt_col,
            qf_using_prep=qf_using_prep,
            primary_severity_pred=primary_severity_pred,
            qf_attach_ctx=qf_attach_ctx,
            params=params,
            new_param=new_param,
        )
