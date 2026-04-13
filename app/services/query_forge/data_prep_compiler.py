"""DataPrep CTE compilation — extracted from QueryForgeService.

Moves: _compile_data_prep_meta, _build_prep_base_selects, _qf_compile_dp_cte,
       _render_data_prep_cte, _dp_ident (the last now lives in sql_utils).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from app.exceptions.forge_error import ForgeError
from app.services.query_forge.sql_utils import (
    col_expr,
    dp_ident,
    literal_sql,
    safe_ident,
)
from app.services.query_forge.types import CompilationContext


class DataPrepCompiler:
    """Stateless — no constructor args.  Instantiate fresh per call."""

    def compile(
        self,
        *,
        query_json: Dict[str, Any],
        alias_by_wt: Dict[int, str],
        qf_base_alias: str,
    ) -> Tuple[str, CompilationContext]:
        """Return (cte_sql, CompilationContext).

        When the query has no DataPrep section, returns ("", empty context).
        """
        data_prep = query_json.get("dataPrep") if isinstance(query_json, dict) else None
        meta = self._compile_meta(
            data_prep,
            qf_base_alias=qf_base_alias,
            alias_by_wt=alias_by_wt,
        )

        context = CompilationContext(
            derived_by_exprid={
                **meta.get("derived_by_exprid", {}),
                **meta.get("computed_alias_by_expr_id", {}),
            },
            derived_by_name=meta.get("derived_by_name", {}),
            rewrite_by_colname=meta.get("rewrite_by_colname", {}),
            rewrite_by_modelid=meta.get("rewrite_by_modelid", {}),
            rewrite_by_wt_col=meta.get("rewrite_by_wt_col", {}),
        )

        exprs = meta.get("exprs") or []
        if not exprs:
            return "", context

        base_selects = [f"{safe_ident(qf_base_alias)}.*"] if qf_base_alias else ["*"]
        cte_sql = self._render_cte(
            base_from_sql=safe_ident(qf_base_alias),
            base_selects=base_selects,
            exprs=exprs,
        )
        return cte_sql, context

    # ------------------------------------------------------------------
    # Internal helpers (extracted from QueryForgeService)
    # ------------------------------------------------------------------

    def _compile_meta(
        self,
        data_prep: Any,
        qf_base_alias: str,
        alias_by_wt: Dict[int, str],
    ) -> Dict[str, Any]:
        if not data_prep or not isinstance(data_prep, dict):
            return {
                "exprs": [],
                "derived_by_exprid": {},
                "computed_alias_by_expr_id": {},
                "derived_by_name": {},
                "rewrite_by_colname": {},
                "rewrite_by_modelid": {},
                "rewrite_by_wt_col": {},
            }

        rules = data_prep.get("rules") or []
        if not isinstance(rules, list) or not rules:
            return {
                "exprs": [],
                "derived_by_exprid": {},
                "computed_alias_by_expr_id": {},
                "derived_by_name": {},
                "rewrite_by_colname": {},
                "rewrite_by_modelid": {},
                "rewrite_by_wt_col": {},
            }

        derived_by_exprid: Dict[str, str] = {}
        computed_alias_by_expr_id: Dict[str, str] = {}
        derived_by_name: Dict[str, str] = {}
        rewrite_by_colname: Dict[str, str] = {}
        rewrite_by_modelid: Dict[int, str] = {}
        rewrite_by_wt_col: Dict[tuple, str] = {}

        exprs: List[str] = []
        qf_using_prep = False

        def _normalize_date_fmt(fmt: Any) -> Optional[str]:
            if fmt is None:
                return None
            if not isinstance(fmt, str):
                raise ForgeError("parse_date.format must be string or null", status_code=400)
            s = fmt.strip()
            if s.startswith("(") and s.endswith(")"):
                s = s[1:-1].strip()
            if not s:
                return None
            return s.lower()

        def _col(ref: Any) -> str:
            return col_expr(
                ref,
                derived_by_exprid,
                derived_by_name,
                rewrite_by_colname,
                rewrite_by_modelid,
                qf_using_prep,
                qf_base_alias,
                alias_by_wt,
                rewrite_by_wt_col=rewrite_by_wt_col,
            )

        for i, r in enumerate(rules):
            if not isinstance(r, dict):
                raise ForgeError(f"dataPrep.rules[{i}] must be an object", status_code=400)

            op = (r.get("op") or "").strip()
            rid = r.get("id")
            if not rid or not isinstance(rid, str):
                raise ForgeError(f"dataPrep.rules[{i}].id is required", status_code=400)

            target = r.get("target")
            output = r.get("output")
            if not isinstance(output, dict):
                raise ForgeError(f"dataPrep.rules[{i}].output must be a column key", status_code=400)
            if op != "concat" and not isinstance(target, dict):
                raise ForgeError(f"dataPrep.rules[{i}].target must be a column key", status_code=400)

            qf_out_name = output.get("columnName")
            if not qf_out_name or not isinstance(qf_out_name, str):
                raise ForgeError(f"dataPrep.rules[{i}].output.columnName is required", status_code=400)

            qf_out_ident = dp_ident(qf_out_name)

            target_expr = None
            if op != "concat":
                target_expr = _col(target)

            if op == "fill_empty":
                treat_blank = bool(r.get("treatBlankAsEmpty"))
                val = r.get("value")
                fb = r.get("fallbackCol")
                base = target_expr
                if treat_blank:
                    base = f"NULLIF(TRIM({target_expr}), '')"
                if fb:
                    fb_expr = _col(fb)
                    expr = f"COALESCE({base}, {fb_expr})"
                else:
                    expr = f"COALESCE({base}, {literal_sql(val)})"
                exprs.append(f"{expr} AS {qf_out_ident}")

            elif op == "cast":
                to_type = r.get("toType")
                if not to_type or not isinstance(to_type, str):
                    raise ForgeError("cast.toType is required", status_code=400)
                safe = bool(r.get("safe"))
                if safe:
                    exprs.append(f"TRY_CAST({target_expr} AS {to_type}) AS {qf_out_ident}")
                else:
                    exprs.append(f"CAST({target_expr} AS {to_type}) AS {qf_out_ident}")

            elif op == "normalize_text":
                mode = r.get("mode")
                if mode not in ("lower", "upper", "trim", "trim_lower"):
                    raise ForgeError("normalize_text.mode invalid", status_code=400)
                if mode == "lower":
                    exprs.append(f"LOWER({target_expr}) AS {qf_out_ident}")
                elif mode == "upper":
                    exprs.append(f"UPPER({target_expr}) AS {qf_out_ident}")
                elif mode == "trim":
                    exprs.append(f"TRIM({target_expr}) AS {qf_out_ident}")
                else:
                    exprs.append(f"LOWER(TRIM({target_expr})) AS {qf_out_ident}")

            elif op == "parse_date":
                fmt = _normalize_date_fmt(r.get("format", None))
                if fmt:
                    exprs.append(f"TO_DATE({target_expr}, {literal_sql(fmt)}) AS {qf_out_ident}")
                else:
                    exprs.append(f"TO_DATE({target_expr}) AS {qf_out_ident}")

            elif op == "date_part":
                part = (r.get("part") or "").strip().lower()
                if part not in ("year", "month", "day"):
                    raise ForgeError("date_part.part must be year|month|day", status_code=400)
                fn_name = part.upper()
                exprs.append(f"{fn_name}({target_expr}) AS {qf_out_ident}")

            elif op == "round":
                dec = r.get("decimals")
                if dec is None or not isinstance(dec, int):
                    raise ForgeError("round.decimals must be an integer", status_code=400)
                exprs.append(f"ROUND({target_expr}, {int(dec)}) AS {qf_out_ident}")

            elif op == "concat":
                inputs = r.get("inputs")
                if not isinstance(inputs, list) or not inputs:
                    raise ForgeError("concat.inputs must be a non-empty list", status_code=400)
                separator = r.get("separator")
                if separator is None:
                    separator = ""
                if not isinstance(separator, str):
                    raise ForgeError("concat.separator must be a string or null", status_code=400)
                sep_sql = literal_sql(separator)
                nulls_mode = (r.get("nulls") or "skip").strip().lower()
                if nulls_mode not in ("skip", "propagate", "empty"):
                    raise ForgeError("concat.nulls must be skip|propagate|empty", status_code=400)
                parts: List[str] = []
                for j, ref in enumerate(inputs):
                    if not isinstance(ref, dict):
                        raise ForgeError(f"concat.inputs[{j}] must be an object", status_code=400)
                    ref_type = (ref.get("type") or "").strip().lower()
                    if ref_type == "column":
                        expr = _col(ref.get("col"))
                    elif ref_type == "literal":
                        expr = literal_sql(ref.get("value"))
                    else:
                        raise ForgeError("concat.inputs type must be column or literal", status_code=400)
                    if nulls_mode == "empty":
                        expr = f"COALESCE({expr}, '')"
                    parts.append(expr)
                if nulls_mode == "skip":
                    qf_expr_sql = f"CONCAT_WS({sep_sql}, {', '.join(parts)})"
                else:
                    if separator:
                        interleaved: List[str] = []
                        for idx, part_expr in enumerate(parts):
                            if idx:
                                interleaved.append(sep_sql)
                            interleaved.append(part_expr)
                        qf_expr_sql = f"CONCAT({', '.join(interleaved)})"
                    else:
                        qf_expr_sql = f"CONCAT({', '.join(parts)})"
                exprs.append(f"{qf_expr_sql} AS {qf_out_ident}")

            else:
                raise ForgeError(f"Unsupported dataPrep op: {op}", status_code=400)

            derived_by_exprid[rid] = qf_out_ident
            out_expr_id = output.get("exprId")
            if out_expr_id and isinstance(out_expr_id, str):
                computed_alias_by_expr_id[out_expr_id] = qf_out_ident
            derived_by_name[qf_out_name] = qf_out_ident

            if isinstance(target, dict):
                tgt_name = target.get("columnName")
                if isinstance(tgt_name, str) and tgt_name:
                    rewrite_by_colname[tgt_name] = qf_out_ident
                tgt_id = target.get("modelColumnId")
                if isinstance(tgt_id, int):
                    rewrite_by_modelid[tgt_id] = qf_out_ident

        if not exprs:
            return {
                "exprs": [],
                "derived_by_exprid": {},
                "computed_alias_by_expr_id": {},
                "derived_by_name": {},
                "rewrite_by_colname": {},
                "rewrite_by_modelid": {},
                "rewrite_by_wt_col": {},
            }

        return {
            "exprs": exprs,
            "derived_by_exprid": derived_by_exprid,
            "computed_alias_by_expr_id": computed_alias_by_expr_id,
            "derived_by_name": derived_by_name,
            "rewrite_by_colname": rewrite_by_colname,
            "rewrite_by_modelid": rewrite_by_modelid,
            "rewrite_by_wt_col": rewrite_by_wt_col,
        }

    def _render_cte(
        self,
        *,
        base_from_sql: str,
        base_selects: List[str],
        exprs: List[str],
        base_where_sql: str = "",
    ) -> str:
        if not exprs:
            return ""
        select_exprs = list(base_selects or [])
        select_exprs.extend(exprs)
        joined = ",\n    ".join(select_exprs)
        sql = (
            "WITH prep AS (\n"
            "  SELECT\n"
            f"    {joined}\n"
            f"  FROM {base_from_sql}\n"
        )
        if base_where_sql:
            sql += f"  WHERE {base_where_sql}\n"
        sql += ")"
        return sql

    def build_prep_base_selects(
        self,
        required_cols: List[Dict[str, Any]],
        *,
        primary_id: int,
        qf_base_alias: str,
        alias_by_wt: Dict[int, str],
    ) -> Tuple[List[str], Dict[str, str], Dict[int, str], Dict[tuple, str]]:
        """Compute explicit SELECT expressions for the prep CTE base columns.

        Returns (base_selects, by_colname, by_modelid, by_wt_col).
        Stays on this class so the orchestration core can call it after
        determining required_cols.
        """
        if not required_cols:
            return [], {}, {}, {}

        name_counts: Dict[str, int] = {}
        refs_by_name: Dict[str, List[Dict[str, Any]]] = {}
        for c in required_cols:
            cn = c.get("columnName") or ""
            name_counts[cn] = name_counts.get(cn, 0) + 1
            refs_by_name.setdefault(cn, []).append(c)

        used: set = set()

        def unique_name(base: str) -> str:
            key = base.lower()
            if key not in used:
                used.add(key)
                return base
            i = 2
            while True:
                candidate = f"{base}_{i}"
                key = candidate.lower()
                if key not in used:
                    used.add(key)
                    return candidate
                i += 1

        base_selects_out: List[str] = []
        by_colname: Dict[str, str] = {}
        by_modelid: Dict[int, str] = {}
        by_wt_col: Dict[tuple, str] = {}

        for c in required_cols:
            cn = c.get("columnName")
            if not cn:
                continue
            wt_id = c.get("workspaceTableId")
            if wt_id is None:
                wt_id = primary_id
            try:
                wt_id_int = int(wt_id)
            except (TypeError, ValueError):
                continue

            alias = alias_by_wt.get(wt_id_int) or (qf_base_alias if wt_id_int == primary_id else None)
            if not alias:
                raise ForgeError("workspaceTableId is not in domain", status_code=400)

            qf_alias_hint = alias_by_wt.get(wt_id_int) or (
                qf_base_alias if wt_id_int == primary_id else f"t{wt_id_int}"
            )
            qf_out_name = cn
            if name_counts.get(cn, 0) > 1:
                if wt_id_int != primary_id:
                    qf_out_name = f"{qf_alias_hint}_{cn}"
            qf_out_name = unique_name(qf_out_name)

            base_selects_out.append(
                f"{safe_ident(alias)}.{safe_ident(cn)} AS {safe_ident(qf_out_name)}"
            )
            mid = c.get("modelColumnId")
            if isinstance(mid, int):
                by_modelid[mid] = qf_out_name
            by_wt_col[(wt_id_int, cn)] = qf_out_name

        for cn, refs in refs_by_name.items():
            chosen = None
            for r in refs:
                if int(r.get("workspaceTableId") or primary_id) == primary_id:
                    chosen = r
                    break
            if not chosen and len(refs) == 1:
                chosen = refs[0]
            if not chosen:
                continue
            wt_id = int(chosen.get("workspaceTableId") or primary_id)
            mapped = by_wt_col.get((wt_id, cn))
            if mapped:
                by_colname[cn] = mapped

        return base_selects_out, by_colname, by_modelid, by_wt_col
