from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from app.exceptions.forge_error import ForgeError
from app.services.domain_resolver import DomainPlan


@dataclass(frozen=True)
class QueryForgeProjectionResult:
    select_exprs: List[str]
    group_by_exprs: List[str]
    qf_output_cols: List[Dict[str, Any]]
    order_alias_by_key: Dict[tuple, str]
    metric_alias_by_ref: Dict[str, str]
    output_names: Dict[str, bool]


class QueryForgeProjectionCompiler:
    def __init__(
        self,
        *,
        col_expr: Callable[..., str],
        compile_metric: Callable[..., str],
        safe_alias: Callable[[str], str],
        col_label_key: Callable[[Any], str],
    ) -> None:
        self._col_expr = col_expr
        self._compile_metric = compile_metric
        self._safe_alias = safe_alias
        self._col_label_key = col_label_key

    def compile(
        self,
        *,
        raw_cols: List[Dict[str, Any]],
        aggs: Dict[str, Any],
        distinct: bool,
        plan: DomainPlan,
        derived_by_exprid: Dict[str, str],
        derived_by_name: Dict[str, str],
        rewrite_by_colname: Dict[str, str],
        rewrite_by_modelid: Dict[int, str],
        rewrite_by_wt_col: Dict[tuple, str],
        qf_using_prep: bool,
        qf_base_alias: str,
        alias_by_wt: Dict[int, str],
    ) -> QueryForgeProjectionResult:
        cols = self._dedupe_projection(raw_cols)

        alias_by_col: Dict[str, str] = {}
        for col in cols:
            column_name = col.get("columnName")
            alias = col.get("alias")
            wt_id = col.get("workspaceTableId")
            if column_name and alias:
                key = f"{wt_id}:{column_name}" if wt_id is not None else str(column_name)
                alias_by_col[str(key)] = str(alias)

        select_exprs: List[str] = []
        group_by_exprs: List[str] = []
        output_names: Dict[str, bool] = {}
        qf_output_cols: List[Dict[str, Any]] = []
        order_alias_by_key: Dict[tuple, str] = {}
        metric_alias_by_ref: Dict[str, str] = {}

        if aggs and bool(aggs.get("enabled")):
            if distinct:
                raise ForgeError("distinct is not supported with aggregations", status_code=400)
            group_by = aggs.get("groupBy") or []
            group_by_exprs = [
                self._col_expr(
                    group,
                    derived_by_exprid,
                    derived_by_name,
                    rewrite_by_colname,
                    rewrite_by_modelid,
                    qf_using_prep,
                    qf_base_alias,
                    alias_by_wt,
                    rewrite_by_wt_col=rewrite_by_wt_col,
                )
                for group in group_by
            ]

            for raw_group, group_expr in zip(group_by, group_by_exprs):
                raw_name = self._col_label_key(raw_group)
                raw_key = f"{raw_group.get('workspaceTableId')}:{raw_name}" if isinstance(raw_group, dict) else raw_name
                user_alias = alias_by_col.get(raw_key)
                alias_hint = None
                if isinstance(raw_group, dict):
                    wt_id = raw_group.get("workspaceTableId")
                    if wt_id is not None:
                        try:
                            alias_hint = alias_by_wt.get(int(wt_id))
                        except Exception:
                            alias_hint = None
                alias_hint = alias_hint or self._alias_hint_from_expr(group_expr)
                output_name = self._reserve_output_name(output_names, user_alias or raw_name, alias_hint)
                select_exprs.append(f"{group_expr} AS {self._safe_alias(output_name)}")
                qf_output_cols.append({"key": output_name, "label": output_name})
                key = self._col_key_for_map(raw_group)
                if key and key not in order_alias_by_key:
                    order_alias_by_key[key] = output_name

            for metric in (aggs.get("metrics") or []):
                fn = (metric.get("fn") or "").lower().strip()
                field = metric.get("field")
                expr = metric.get("expr")
                label = metric.get("label")
                metric_ref = str(metric.get("metric_ref") or metric.get("metricRef") or metric.get("id") or "").strip().lower()
                metric_sql = self._compile_metric(
                    fn,
                    field,
                    derived_by_exprid,
                    derived_by_name,
                    rewrite_by_colname,
                    rewrite_by_modelid,
                    qf_using_prep,
                    qf_base_alias,
                    alias_by_wt,
                    rewrite_by_wt_col=rewrite_by_wt_col,
                    expr=expr,
                )
                output_name = self._reserve_output_name(output_names, label or fn or "metric", None)
                select_exprs.append(f"{metric_sql} AS {self._safe_alias(output_name)}")
                qf_output_cols.append({"key": output_name, "label": output_name})
                if metric_ref:
                    metric_alias_by_ref[metric_ref] = output_name
        else:
            name_counts: Dict[str, int] = {}
            for col in cols:
                column_name = col.get("columnName")
                if column_name:
                    name_counts[column_name] = name_counts.get(column_name, 0) + 1

            alias_by_wt_table: Dict[int, str] = {table.workspace_table_id: table.table_alias or table.alias for table in plan.tables}
            for col in cols:
                desired_name = col.get("columnName")
                user_alias = col.get("alias")
                wt_id = col.get("workspaceTableId")
                expr_id = col.get("exprId")
                expr_sql = self._col_expr(
                    col,
                    derived_by_exprid,
                    derived_by_name,
                    rewrite_by_colname,
                    rewrite_by_modelid,
                    qf_using_prep,
                    qf_base_alias,
                    alias_by_wt,
                    rewrite_by_wt_col=rewrite_by_wt_col,
                )

                alias_hint = None
                if wt_id is not None:
                    try:
                        alias_hint = alias_by_wt_table.get(int(wt_id))
                    except Exception:
                        alias_hint = None
                if expr_id and not alias_hint:
                    alias_hint = self._alias_hint_from_expr(expr_sql)

                base_output_name = user_alias or desired_name
                if not user_alias and desired_name and name_counts.get(desired_name, 0) > 1:
                    alias_base = alias_hint or qf_base_alias
                    base_output_name = f"{alias_base}_{desired_name}"

                output_name = self._reserve_output_name(output_names, base_output_name, alias_hint)
                select_exprs.append(f"{expr_sql} AS {self._safe_alias(output_name)}")
                key = self._col_key_for_map(col)
                if key and key not in order_alias_by_key:
                    order_alias_by_key[key] = output_name
                qf_output_cols.append({"key": output_name, "label": output_name})

        return QueryForgeProjectionResult(
            select_exprs=select_exprs,
            group_by_exprs=group_by_exprs,
            qf_output_cols=qf_output_cols,
            order_alias_by_key=order_alias_by_key,
            metric_alias_by_ref=metric_alias_by_ref,
            output_names=output_names,
        )

    @staticmethod
    def merge_attachment_selects(
        projection: QueryForgeProjectionResult,
        attachment_selects: List[Any],
        *,
        aggs_enabled: bool,
    ) -> QueryForgeProjectionResult:
        if attachment_selects and aggs_enabled:
            raise ForgeError("Attachments with projectFields require non-aggregated queries", status_code=400)

        select_exprs = list(projection.select_exprs)
        qf_output_cols = list(projection.qf_output_cols)
        output_names = dict(projection.output_names)

        for expr, output_name in attachment_selects:
            if output_name:
                key = output_name.lower()
                if output_names.get(key):
                    continue
                output_names[key] = True
            select_exprs.append(expr)
            if output_name:
                qf_output_cols.append({"key": output_name, "label": output_name})

        return QueryForgeProjectionResult(
            select_exprs=select_exprs,
            group_by_exprs=projection.group_by_exprs,
            qf_output_cols=qf_output_cols,
            order_alias_by_key=projection.order_alias_by_key,
            metric_alias_by_ref=projection.metric_alias_by_ref,
            output_names=output_names,
        )

    @staticmethod
    def _dedupe_projection(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        seen: set[tuple] = set()
        out: List[Dict[str, Any]] = []
        for col in items:
            expr_id = col.get("exprId")
            if expr_id:
                key = ("expr", expr_id)
            else:
                key = (
                    "col",
                    col.get("workspaceTableId"),
                    col.get("modelColumnId"),
                    col.get("columnName"),
                )
            if key in seen:
                continue
            seen.add(key)
            out.append(col)
        return out

    @staticmethod
    def _alias_hint_from_expr(expr_sql: str) -> Optional[str]:
        if not isinstance(expr_sql, str):
            return None
        match = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_]*)$", expr_sql)
        return match.group(1) if match else None

    @staticmethod
    def _col_key_for_map(value: Any) -> Optional[tuple]:
        if isinstance(value, dict):
            expr_id = value.get("exprId")
            if expr_id:
                return ("expr", str(expr_id))
            return ("col", value.get("workspaceTableId"), value.get("modelColumnId"), value.get("columnName"))
        if isinstance(value, str):
            return ("col", None, None, value.strip())
        return None

    @staticmethod
    def _reserve_output_name(
        output_names: Dict[str, bool],
        base_name: str | None,
        alias_hint: Optional[str],
    ) -> str:
        base = (base_name or "").strip() or "col"
        key = base.lower()
        if not output_names.get(key):
            output_names[key] = True
            return base
        if alias_hint:
            candidate = f"{alias_hint}_{base}"
            key = candidate.lower()
            if not output_names.get(key):
                output_names[key] = True
                return candidate
            prefix = candidate
        else:
            prefix = base
        idx = 2
        while True:
            candidate = f"{prefix}_{idx}"
            key = candidate.lower()
            if not output_names.get(key):
                output_names[key] = True
                return candidate
            idx += 1
