"""Split-ratio metric compilation — extracted from QueryForgeService.

Moves: _detect_split_ratio_metric, _compile_split_ratio_query.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.exceptions.forge_error import ForgeError
from app.services.query_forge.types import ForgeCompiledQuery


def detect_split_ratio_metric(
    query_json: Dict[str, Any],
    *,
    primary_id: int,
) -> Optional[Dict[str, Any]]:
    """Return the split-ratio metric dict if the query uses one, else None.

    Raises ForgeError if the query has more than one ratio metric or mixes
    ratio metrics with other aggregation metrics.
    """
    aggs = query_json.get("aggs") or {}
    if not bool(aggs.get("enabled")):
        return None
    metrics = aggs.get("metrics") or []
    ratio_metrics: List[Dict[str, Any]] = []
    for metric in metrics:
        if not isinstance(metric, dict):
            continue
        if str(metric.get("fn") or "").strip().lower() != "expr":
            continue
        expr = metric.get("expr")
        if not isinstance(expr, dict):
            continue
        if str(expr.get("kind") or "").strip().lower() != "ratio":
            continue
        numerator = expr.get("numerator") or {}
        denominator = expr.get("denominator") or {}
        if not isinstance(numerator, dict) or not isinstance(denominator, dict):
            continue
        n_field = numerator.get("field")
        d_field = denominator.get("field")
        if not isinstance(n_field, dict) or not isinstance(d_field, dict):
            continue
        try:
            n_table = int(n_field.get("workspaceTableId") or primary_id)
            d_table = int(d_field.get("workspaceTableId") or primary_id)
        except (TypeError, ValueError):
            continue
        if n_table != d_table:
            ratio_metrics.append(metric)

    if not ratio_metrics:
        return None
    if len(ratio_metrics) > 1:
        raise ForgeError(
            "derived_validation_failed: unsupported_split_ratio_metric_mix at aggs.metrics",
            status_code=400,
            details={
                "issues": [
                    {
                        "code": "unsupported_split_ratio_metric_mix",
                        "path": "aggs.metrics",
                        "message": "Only one split ratio metric is supported per query",
                    }
                ]
            },
        )
    if len(metrics) > 1:
        raise ForgeError(
            "derived_validation_failed: unsupported_split_ratio_metric_mix at aggs.metrics",
            status_code=400,
            details={
                "issues": [
                    {
                        "code": "unsupported_split_ratio_metric_mix",
                        "path": "aggs.metrics",
                        "message": "Split ratio metrics cannot be mixed with other aggregate metrics",
                    }
                ]
            },
        )
    return ratio_metrics[0]


def is_split_ratio_query(query_json: Dict[str, Any], *, primary_id: int) -> bool:
    """Return True if *query_json* describes a split-ratio metric pattern."""
    try:
        return detect_split_ratio_metric(query_json, primary_id=primary_id) is not None
    except ForgeError:
        raise


class SplitRatioCompiler:
    """Stateless — no constructor args.

    The full compile() method signature is defined here but the heavy
    orchestration (FROM clause, join resolution) still delegates to
    callbacks provided by the service until Phase 8 completes.
    """

    def compile(
        self,
        *,
        query_json: Dict[str, Any],
        split_metric: Dict[str, Any],
        primary_id: int,
        qf_base_alias: str,
        alias_by_wt: Dict[int, str],
        mode: str,
        limit: int,
        offset: int,
        compile_where_fn: Any,
        from_clause_fn: Any,
        required_table_ids_fn: Any,
        compile_metric_fn: Any,
        severity_pred: str = "",
        severity_table_ids: Optional[Any] = None,
    ) -> ForgeCompiledQuery:
        """Compile the split-ratio metric path into a ForgeCompiledQuery.

        Callbacks (compile_where_fn, from_clause_fn, etc.) are service-level
        methods passed from the orchestration core so this module has no
        import dependency on service.py.
        """
        from app.services.query_forge.where_compiler import (
            build_and_filter_tree,
            flatten_and_conditions,
            is_and_only_filter_tree,
        )
        import re

        if severity_table_ids is None:
            severity_table_ids = set()

        if bool(query_json.get("distinct", False)):
            raise ForgeError("distinct is not supported with aggregations", status_code=400)
        if query_json.get("dataPrep"):
            raise ForgeError("Split ratio compilation does not support dataPrep", status_code=400)
        if query_json.get("value_overrideAttachments") or query_json.get("cohortAttachment"):
            raise ForgeError("Split ratio compilation does not support attachments", status_code=400)

        aggs = query_json.get("aggs") or {}
        group_by = aggs.get("groupBy") or []

        if not is_and_only_filter_tree(query_json.get("filters")):
            raise ForgeError(
                "derived_validation_failed: unsupported_filter_tree_for_split_ratio at filters",
                status_code=400,
                details={
                    "issues": [
                        {
                            "code": "unsupported_filter_tree_for_split_ratio",
                            "path": "filters",
                            "message": "Split ratio queries support deterministic AND-only global filters",
                        }
                    ]
                },
            )

        expr = split_metric.get("expr") or {}
        numerator = expr.get("numerator") or {}
        denominator = expr.get("denominator") or {}
        num_field = numerator.get("field") or {}
        den_field = denominator.get("field") or {}
        try:
            num_table_id = int(num_field.get("workspaceTableId") or primary_id)
            den_table_id = int(den_field.get("workspaceTableId") or primary_id)
        except (TypeError, ValueError):
            raise ForgeError("Invalid ratio metric table bindings", status_code=400)

        all_conditions = flatten_and_conditions(query_json.get("filters"))
        num_conditions: List[Dict[str, Any]] = []
        den_conditions: List[Dict[str, Any]] = []
        for cond in all_conditions:
            field = cond.get("field")
            wt_id = field.get("workspaceTableId") if isinstance(field, dict) else None
            if wt_id is None:
                wt_id = primary_id
            try:
                wt_id_int = int(wt_id)
            except (TypeError, ValueError):
                wt_id_int = primary_id
            if wt_id_int == num_table_id:
                num_conditions.append(cond)
            elif wt_id_int == den_table_id:
                den_conditions.append(cond)
            else:
                num_conditions.append(cond)
                den_conditions.append(cond)

        if is_and_only_filter_tree(numerator.get("filters")):
            num_conditions.extend(flatten_and_conditions(numerator.get("filters")))
        elif numerator.get("filters") is not None:
            raise ForgeError(
                "derived_validation_failed: unsupported_filter_tree_for_split_ratio "
                "at aggs.metrics[0].expr.numerator.filters",
                status_code=400,
            )

        if is_and_only_filter_tree(denominator.get("filters")):
            den_conditions.extend(flatten_and_conditions(denominator.get("filters")))
        elif denominator.get("filters") is not None:
            raise ForgeError(
                "derived_validation_failed: unsupported_filter_tree_for_split_ratio "
                "at aggs.metrics[0].expr.denominator.filters",
                status_code=400,
            )

        num_filter_tree = build_and_filter_tree(num_conditions)
        den_filter_tree = build_and_filter_tree(den_conditions)

        params: Dict[str, Any] = {}
        param_counter = 0

        def new_param(val: Any) -> str:
            nonlocal param_counter
            param_counter += 1
            key = f"p{param_counter}"
            params[key] = val
            return f":{key}"

        from app.services.query_forge.sql_utils import col_expr, safe_alias, safe_ident

        grain_aliases: List[str] = []
        grain_exprs: List[str] = []
        used_aliases: set = set()
        for idx, gb in enumerate(group_by):
            qf_expr_sql = col_expr(gb, {}, {}, {}, {}, False, qf_base_alias, alias_by_wt)
            col_name = str((gb or {}).get("columnName") or f"group_{idx+1}").strip() or f"group_{idx+1}"
            wt_id = (gb or {}).get("workspaceTableId")
            if isinstance(wt_id, int):
                alias = f"wt{wt_id}_{col_name}"
            else:
                alias = col_name
            alias = re.sub(r"[^A-Za-z0-9_]+", "_", alias).strip("_") or f"group_{idx+1}"
            if alias[0].isdigit():
                alias = f"g_{alias}"
            base = alias
            inc = 2
            while alias.lower() in used_aliases:
                alias = f"{base}_{inc}"
                inc += 1
            used_aliases.add(alias.lower())
            grain_aliases.append(alias)
            grain_exprs.append(qf_expr_sql)

        def build_side_cte(
            *,
            cte_name: str,
            metric_part: Dict[str, Any],
            metric_table_id: int,
            filters_node: Optional[Dict[str, Any]],
            value_alias: str,
        ) -> str:
            metric_field = metric_part.get("field")
            metric_fn = str(metric_part.get("fn") or "").strip().lower()
            if not isinstance(metric_field, dict):
                raise ForgeError("Split ratio metric side must include a field", status_code=400)

            side_query: Dict[str, Any] = {
                "columns": [],
                "aggs": {"enabled": True, "groupBy": group_by, "metrics": [{"fn": metric_fn, "field": metric_field}]},
                "sorting": [],
                "filters": filters_node,
                "dataPrep": None,
                "value_overrideAttachments": [],
                "cohortAttachment": None,
            }
            required_table_ids = required_table_ids_fn(side_query)
            required_table_ids.add(int(metric_table_id))
            from_sql = from_clause_fn(required_table_ids, severity_table_ids=severity_table_ids)

            where_sql, exists_parts = compile_where_fn(
                filters_node,
                {},
                {},
                {},
                {},
                False,
                qf_base_alias,
                alias_by_wt,
                new_param,
                severity_table_ids=severity_table_ids,
            )
            where_parts = [p for p in ([where_sql] if where_sql else []) + exists_parts if p]
            if severity_pred:
                where_parts.insert(0, severity_pred)

            metric_sql = compile_metric_fn(metric_fn, metric_field, {}, {}, {}, {}, False, qf_base_alias, alias_by_wt)
            selects = [f"{expr_s} AS {safe_alias(al)}" for expr_s, al in zip(grain_exprs, grain_aliases)]
            selects.append(f"{metric_sql} AS {safe_alias(value_alias)}")
            side_sql = f"{safe_ident(cte_name)} AS (\n  SELECT {', '.join(selects)}\n  FROM {from_sql}"
            if where_parts:
                side_sql += f"\n  WHERE {' AND '.join(where_parts)}"
            if grain_exprs:
                side_sql += f"\n  GROUP BY {', '.join(grain_exprs)}"
            side_sql += "\n)"
            return side_sql

        num_cte = build_side_cte(
            cte_name="num",
            metric_part=numerator,
            metric_table_id=num_table_id,
            filters_node=num_filter_tree,
            value_alias="num_val",
        )
        den_cte = build_side_cte(
            cte_name="den",
            metric_part=denominator,
            metric_table_id=den_table_id,
            filters_node=den_filter_tree,
            value_alias="den_val",
        )

        metric_name = str(expr.get("name") or split_metric.get("id") or "derived_ratio")
        metric_label = str(split_metric.get("label") or metric_name or "derived_ratio")
        ratio_expr_str = (
            "num.num_val / NULLIF(den.den_val, 0)"
            if bool(expr.get("safe_divide", True))
            else "num.num_val / den.den_val"
        )
        multiply_by = expr.get("multiply_by")
        if isinstance(multiply_by, (int, float)):
            ratio_expr_str = f"({ratio_expr_str}) * {float(multiply_by)}"

        select_list = [f"num.{safe_ident(al)} AS {safe_alias(al)}" for al in grain_aliases]
        select_list.append(f"{ratio_expr_str} AS {safe_alias(metric_label)}")

        debug_enabled = bool(((query_json.get("meta") or {}).get("debug")))
        if debug_enabled:
            select_list.append("num.num_val AS numerator_value")
            select_list.append("den.den_val AS denominator_value")

        if grain_aliases:
            join_on = " AND ".join(
                f"num.{safe_ident(al)} = den.{safe_ident(al)}" for al in grain_aliases
            )
        else:
            join_on = "1=1"

        base_sql = (
            f"WITH {num_cte},\n{den_cte}\n"
            f"SELECT {', '.join(select_list)}\n"
            "FROM num\n"
            f"LEFT JOIN den ON {join_on}"
        )
        qf_count_sql = f"SELECT COUNT(*) AS total FROM (\n{base_sql}\n) q"

        order_sql = ""
        for entry in (query_json.get("sorting") or []):
            if not isinstance(entry, dict):
                continue
            col = entry.get("col") if "col" in entry else entry.get("columnName")
            direction = str(entry.get("dir") or "asc").strip().lower()
            if direction not in ("asc", "desc"):
                continue
            alias = None
            if isinstance(col, dict):
                cn = str(col.get("columnName") or "").strip()
                if cn in grain_aliases:
                    alias = cn
            elif isinstance(col, str) and col.strip() in grain_aliases:
                alias = col.strip()
            if alias:
                order_sql = f"{safe_alias(alias)} {direction.upper()}"
                break
        if not order_sql and grain_aliases:
            order_sql = ", ".join(f"{safe_alias(al)} ASC" for al in grain_aliases)

        sql = base_sql
        if order_sql:
            sql += f"\nORDER BY {order_sql}"
        if mode == "preview":
            sql += f"\nLIMIT {int(limit)}\nOFFSET {int(offset)}"

        qf_output_cols = [{"key": al, "label": al} for al in grain_aliases]
        qf_output_cols.append({"key": metric_label, "label": metric_label})
        if debug_enabled:
            qf_output_cols.append({"key": "numerator_value", "label": "numerator_value"})
            qf_output_cols.append({"key": "denominator_value", "label": "denominator_value"})
        return ForgeCompiledQuery(sql=sql, qf_count_sql=qf_count_sql, params=params, qf_output_cols=qf_output_cols)
