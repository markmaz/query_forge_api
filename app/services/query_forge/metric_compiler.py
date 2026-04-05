from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from app.exceptions.forge_error import ForgeError


class QueryForgeMetricCompiler:
    def __init__(
        self,
        *,
        col_expr: Callable[..., str],
    ) -> None:
        self._col_expr = col_expr

    def compile(
        self,
        fn: Any,
        field: Any,
        derived_by_exprid: Dict[str, str],
        derived_by_name: Dict[str, str],
        rewrite_by_colname: Dict[str, str],
        rewrite_by_modelid: Dict[int, str],
        qf_using_prep: bool,
        qf_base_alias: str,
        alias_by_wt: Dict[int, str],
        *,
        rewrite_by_wt_col: Optional[Dict[tuple, str]] = None,
        expr: Any = None,
    ) -> str:
        if rewrite_by_wt_col is None:
            rewrite_by_wt_col = {}
        fn = (fn or "").lower().strip()

        if fn == "count":
            if not field:
                return "COUNT(*)"
            col = self._col_expr(
                field,
                derived_by_exprid,
                derived_by_name,
                rewrite_by_colname,
                rewrite_by_modelid,
                qf_using_prep,
                qf_base_alias,
                alias_by_wt,
                rewrite_by_wt_col=rewrite_by_wt_col,
            )
            return f"COUNT({col})"

        if fn == "count_distinct":
            if not field:
                raise ForgeError("count_distinct requires a field", status_code=400)
            col = self._col_expr(
                field,
                derived_by_exprid,
                derived_by_name,
                rewrite_by_colname,
                rewrite_by_modelid,
                qf_using_prep,
                qf_base_alias,
                alias_by_wt,
                rewrite_by_wt_col=rewrite_by_wt_col,
            )
            return f"COUNT(DISTINCT {col})"

        if fn in ("sum", "avg", "min", "max"):
            if not field:
                raise ForgeError(f"{fn} requires a field", status_code=400)
            col = self._col_expr(
                field,
                derived_by_exprid,
                derived_by_name,
                rewrite_by_colname,
                rewrite_by_modelid,
                qf_using_prep,
                qf_base_alias,
                alias_by_wt,
                rewrite_by_wt_col=rewrite_by_wt_col,
            )
            return f"{fn.upper()}({col})"

        if fn == "expr":
            if not isinstance(expr, dict):
                raise ForgeError("expr metric requires expr payload", status_code=400)
            kind = str(expr.get("kind") or "").strip().lower()
            if kind != "ratio":
                raise ForgeError("Unsupported expr metric kind", status_code=400)
            numerator = expr.get("numerator")
            denominator = expr.get("denominator")
            if not isinstance(numerator, dict) or not isinstance(denominator, dict):
                raise ForgeError("expr ratio requires numerator and denominator", status_code=400)
            num_sql = self.compile(
                str(numerator.get("fn") or "").strip().lower(),
                numerator.get("field"),
                derived_by_exprid,
                derived_by_name,
                rewrite_by_colname,
                rewrite_by_modelid,
                qf_using_prep,
                qf_base_alias,
                alias_by_wt,
                rewrite_by_wt_col=rewrite_by_wt_col,
                expr=None,
            )
            den_sql = self.compile(
                str(denominator.get("fn") or "").strip().lower(),
                denominator.get("field"),
                derived_by_exprid,
                derived_by_name,
                rewrite_by_colname,
                rewrite_by_modelid,
                qf_using_prep,
                qf_base_alias,
                alias_by_wt,
                rewrite_by_wt_col=rewrite_by_wt_col,
                expr=None,
            )
            safe_divide = bool(expr.get("safe_divide", True))
            multiply_by = expr.get("multiply_by")
            if safe_divide:
                ratio_sql = f"({num_sql}) / NULLIF(({den_sql}), 0)"
            else:
                ratio_sql = f"({num_sql}) / ({den_sql})"
            if isinstance(multiply_by, (int, float)):
                ratio_sql = f"({ratio_sql}) * {float(multiply_by)}"
            return ratio_sql

        if fn.replace("_", " ").upper() in ("COUNT DISTINCT", "COUNT", "SUM", "AVG", "MIN", "MAX"):
            legacy = fn.replace("_", " ").upper()
            if legacy == "COUNT":
                if not field:
                    return "COUNT(*)"
                col = self._col_expr(
                    field,
                    derived_by_exprid,
                    derived_by_name,
                    rewrite_by_colname,
                    rewrite_by_modelid,
                    qf_using_prep,
                    qf_base_alias,
                    alias_by_wt,
                    rewrite_by_wt_col=rewrite_by_wt_col,
                )
                return f"COUNT({col})"
            if legacy == "COUNT DISTINCT":
                if not field:
                    raise ForgeError("count_distinct requires a field", status_code=400)
                col = self._col_expr(
                    field,
                    derived_by_exprid,
                    derived_by_name,
                    rewrite_by_colname,
                    rewrite_by_modelid,
                    qf_using_prep,
                    qf_base_alias,
                    alias_by_wt,
                    rewrite_by_wt_col=rewrite_by_wt_col,
                )
                return f"COUNT(DISTINCT {col})"
            if legacy in ("SUM", "AVG", "MIN", "MAX"):
                if not field:
                    raise ForgeError(f"{legacy} requires a field", status_code=400)
                col = self._col_expr(
                    field,
                    derived_by_exprid,
                    derived_by_name,
                    rewrite_by_colname,
                    rewrite_by_modelid,
                    qf_using_prep,
                    qf_base_alias,
                    alias_by_wt,
                    rewrite_by_wt_col=rewrite_by_wt_col,
                )
                return f"{legacy}({col})"

        raise ForgeError(f"Unsupported metric fn: {fn}", status_code=400)
