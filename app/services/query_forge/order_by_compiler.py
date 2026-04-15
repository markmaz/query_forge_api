from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from app.exceptions.forge_error import ForgeError


class QueryForgeOrderByCompiler:
    def __init__(
        self,
        *,
        col_expr: Callable[..., str],
        safe_alias: Callable[[str], str],
    ) -> None:
        self._col_expr = col_expr
        self._safe_alias = safe_alias

    def compile(
        self,
        sorting: List[Dict[str, Any]],
        derived_by_exprid: Dict[str, str],
        derived_by_name: Dict[str, str],
        rewrite_by_colname: Dict[str, str],
        rewrite_by_modelid: Dict[int, str],
        qf_using_prep: bool,
        qf_base_alias: str,
        alias_by_wt: Dict[int, str],
        *,
        rewrite_by_wt_col: Optional[Dict[tuple, str]] = None,
        order_alias_by_key: Optional[Dict[tuple, str]] = None,
        metric_alias_by_ref: Optional[Dict[str, str]] = None,
        distinct: bool = False,
    ) -> str:
        if rewrite_by_wt_col is None:
            rewrite_by_wt_col = {}
        if metric_alias_by_ref is None:
            metric_alias_by_ref = {}
        parts: List[str] = []
        for s in sorting:
            if not isinstance(s, dict):
                raise ForgeError("Invalid sorting entry", status_code=400)
            dir_ = (s.get("dir") or "asc").lower()
            if dir_ not in ("asc", "desc"):
                raise ForgeError("Invalid sort direction", status_code=400)

            metric_ref = str(s.get("metricRef") or s.get("metric_ref") or "").strip().lower()
            if metric_ref:
                metric_alias = metric_alias_by_ref.get(metric_ref)
                if metric_alias:
                    parts.append(f"{self._safe_alias(metric_alias)} {dir_.upper()}")
                continue

            col = s.get("col") if "col" in s else s.get("columnName")
            if distinct and order_alias_by_key:
                key = None
                if isinstance(col, dict):
                    expr_id = col.get("exprId")
                    if expr_id:
                        key = ("expr", str(expr_id))
                    else:
                        key = (
                            "col",
                            col.get("workspaceTableId"),
                            col.get("modelColumnId"),
                            col.get("columnName"),
                        )
                elif isinstance(col, str):
                    key = ("col", None, None, col.strip())

                if key:
                    alias = order_alias_by_key.get(key)
                    if alias:
                        parts.append(f"{self._safe_alias(alias)} {dir_.upper()}")
                        continue

            col_expr = self._col_expr(
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

            parts.append(f"{col_expr} {dir_.upper()}")
        return ", ".join(parts)
