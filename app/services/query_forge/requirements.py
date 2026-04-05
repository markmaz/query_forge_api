from __future__ import annotations

from typing import Any, Callable, Dict, List

from app.services.domain_resolver import DomainPlan


class QueryForgeRequirementAnalyzer:
    def __init__(
        self,
        *,
        normalize_col_key: Callable[[Any, str], Dict[str, Any]],
        effective_filter_mode: Callable[[DomainPlan, int], str],
    ) -> None:
        self._normalize_col_key = normalize_col_key
        self._effective_filter_mode = effective_filter_mode

    def required_table_ids_from_query(self, q: Dict[str, Any], plan: DomainPlan) -> set[int]:
        needed: set[int] = {int(plan.primary.workspace_table_id)}

        def add_wt_id(v: Any) -> None:
            if v is None:
                return
            try:
                needed.add(int(v))
            except Exception:
                return

        for c in (q.get("columns") or []):
            if isinstance(c, dict):
                add_wt_id(c.get("workspaceTableId"))

        aggs = q.get("aggs") or {}
        for g in (aggs.get("groupBy") or []):
            if isinstance(g, dict):
                add_wt_id(g.get("workspaceTableId"))
        for m in (aggs.get("metrics") or []):
            field = (m or {}).get("field")
            if isinstance(field, dict):
                add_wt_id(field.get("workspaceTableId"))
            expr = (m or {}).get("expr")
            if isinstance(expr, dict) and str(expr.get("kind") or "").strip().lower() == "ratio":
                numerator = expr.get("numerator")
                denominator = expr.get("denominator")
                if isinstance(numerator, dict) and isinstance(numerator.get("field"), dict):
                    add_wt_id((numerator.get("field") or {}).get("workspaceTableId"))
                if isinstance(denominator, dict) and isinstance(denominator.get("field"), dict):
                    add_wt_id((denominator.get("field") or {}).get("workspaceTableId"))

        for s in (q.get("sorting") or []):
            if isinstance(s, dict):
                col = s.get("col") if "col" in s else s.get("columnName")
                if isinstance(col, dict):
                    add_wt_id(col.get("workspaceTableId"))

        dp = q.get("dataPrep") or {}
        for r in (dp.get("rules") or []):
            if not isinstance(r, dict):
                continue
            tgt = r.get("target")
            fb = r.get("fallbackCol")
            if isinstance(tgt, dict):
                add_wt_id(tgt.get("workspaceTableId"))
            if isinstance(fb, dict):
                add_wt_id(fb.get("workspaceTableId"))

        def walk_filters(n: Any) -> None:
            if not isinstance(n, dict):
                return
            t = n.get("type")
            if t == "group":
                for c in (n.get("children") or []):
                    walk_filters(c)
            elif t == "condition":
                field = n.get("field")
                wt_id = None
                if isinstance(field, dict):
                    wt_id = field.get("workspaceTableId")
                if wt_id is None:
                    wt_id = plan.primary.workspace_table_id
                mode = self._effective_filter_mode(plan, int(wt_id))
                if mode == "WHERE":
                    add_wt_id(wt_id)

        walk_filters(q.get("filters"))
        return needed

    def collect_required_column_keys(
        self,
        q: Dict[str, Any],
        plan: DomainPlan,
        *,
        required_table_ids: set[int],
        derived_by_exprid: Dict[str, str],
        derived_by_name: Dict[str, str],
    ) -> List[Dict[str, Any]]:
        primary_id = int(plan.primary.workspace_table_id)
        out: List[Dict[str, Any]] = []
        seen: set[tuple] = set()

        def add_ref(v: Any, path: str) -> None:
            if v is None:
                return
            norm = self._normalize_col_key(v, path)
            expr_id = norm.get("exprId")
            mid = norm.get("modelColumnId")
            if expr_id:
                if expr_id in derived_by_exprid:
                    return
                if mid is None:
                    return
            col_name = norm.get("columnName")
            if col_name in derived_by_name:
                return
            wt_id = norm.get("workspaceTableId")
            if wt_id is None:
                wt_id = primary_id
            try:
                wt_id_int = int(wt_id)
            except Exception:
                return
            if required_table_ids and wt_id_int not in required_table_ids:
                return
            norm["workspaceTableId"] = wt_id_int
            key = (wt_id_int, norm.get("modelColumnId"), col_name)
            if key in seen:
                return
            seen.add(key)
            out.append(norm)

        for i, c in enumerate(q.get("columns") or []):
            add_ref(c, f"columns[{i}]")

        aggs = q.get("aggs") or {}
        for i, g in enumerate(aggs.get("groupBy") or []):
            add_ref(g, f"aggs.groupBy[{i}]")
        for i, m in enumerate(aggs.get("metrics") or []):
            field = (m or {}).get("field")
            if field is not None:
                add_ref(field, f"aggs.metrics[{i}].field")
            expr = (m or {}).get("expr")
            if isinstance(expr, dict) and str(expr.get("kind") or "").strip().lower() == "ratio":
                numerator = expr.get("numerator")
                denominator = expr.get("denominator")
                if isinstance(numerator, dict) and numerator.get("field") is not None:
                    add_ref(numerator.get("field"), f"aggs.metrics[{i}].expr.numerator.field")
                if isinstance(denominator, dict) and denominator.get("field") is not None:
                    add_ref(denominator.get("field"), f"aggs.metrics[{i}].expr.denominator.field")

        for i, s in enumerate(q.get("sorting") or []):
            if not isinstance(s, dict):
                continue
            col = s.get("col") if "col" in s else s.get("columnName")
            add_ref(col, f"sorting[{i}].col")

        def walk_filters(n: Any) -> None:
            if not isinstance(n, dict):
                return
            t = n.get("type")
            if t == "group":
                for c in (n.get("children") or []):
                    walk_filters(c)
                return
            if t != "condition":
                return
            field = n.get("field")
            wt_id = None
            if isinstance(field, dict):
                wt_id = field.get("workspaceTableId")
            if wt_id is None:
                wt_id = primary_id
            mode = self._effective_filter_mode(plan, int(wt_id))
            if mode == "WHERE":
                add_ref(field, "filters.condition.field")

        walk_filters(q.get("filters"))

        for i, cw in enumerate(q.get("value_overrideAttachments") or []):
            if not isinstance(cw, dict):
                continue
            cols = cw.get("domainJoinColumns") or []
            if not isinstance(cols, list):
                continue
            for j, col in enumerate(cols):
                add_ref(col, f"value_overrideAttachments[{i}].domainJoinColumns[{j}]")

        cohort = q.get("cohortAttachment")
        if isinstance(cohort, dict):
            domain_col = cohort.get("domainJoinColumn")
            if domain_col is not None:
                add_ref(domain_col, "cohortAttachment.domainJoinColumn")

        return out
