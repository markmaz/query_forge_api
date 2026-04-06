"""WHERE clause compilation — extracted from QueryForgeService.

Moves: _compile_where, _is_and_only_filter_tree, _flatten_and_conditions,
       _build_and_filter_tree.
"""
from __future__ import annotations

import ast
import json
from json import JSONDecodeError
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from app.exceptions.forge_error import ForgeError
from app.services.query_forge.sql_utils import col_expr, physical_col_expr, safe_ident
from app.services.query_forge.types import CompilationContext
from app.services.value_overrides.list_schema import TABLE_BY_TYPE

QF_MAX_MANUAL_IN = 150
JSON_LIST_PARSE_ERRORS = (JSONDecodeError,)
LITERAL_LIST_PARSE_ERRORS = (SyntaxError, ValueError)
VALUE_OVERRIDE_IN_COLUMN_BY_TYPE = {
    "regions": "zipcode",
    "npiCategories": "npi",
    "serviceLines": "procedure_code",
}


# ---------------------------------------------------------------------------
# Pure filter-tree helpers (formerly static methods on QueryForgeService)
# ---------------------------------------------------------------------------


def is_and_only_filter_tree(node: Any) -> bool:
    """Return True iff the filter tree contains only AND groups."""
    if not node:
        return True
    if not isinstance(node, dict):
        return False
    t = node.get("type")
    if t == "condition":
        return True
    if t != "group":
        return False
    if (node.get("match") or "and").lower() != "and":
        return False
    children = node.get("children") or []
    if not isinstance(children, list):
        return False
    return all(is_and_only_filter_tree(child) for child in children)


def flatten_and_conditions(node: Any) -> List[Dict[str, Any]]:
    """Flatten an AND-only filter tree into a list of condition dicts."""
    if not node:
        return []
    if not isinstance(node, dict):
        return []
    t = node.get("type")
    if t == "condition":
        return [node]
    if t != "group":
        return []
    out: List[Dict[str, Any]] = []
    for child in (node.get("children") or []):
        out.extend(flatten_and_conditions(child))
    return out


def build_and_filter_tree(conditions: Sequence[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Wrap a list of conditions into an AND group (or return the single item)."""
    clean = [c for c in conditions if isinstance(c, dict)]
    if not clean:
        return None
    if len(clean) == 1:
        return clean[0]
    return {"type": "group", "match": "and", "children": clean}


# ---------------------------------------------------------------------------
# WhereCompiler
# ---------------------------------------------------------------------------


class WhereCompiler:
    """Optional callback-powered WHERE/EXISTS compiler."""

    def __init__(
        self,
        *,
        get_join_path: Optional[Callable[[Any, int], List[Any]]] = None,
        join_predicates: Optional[Callable[[Any, str, str], List[str]]] = None,
        severity_predicate_for_alias: Optional[Callable[..., str]] = None,
        effective_filter_mode: Optional[Callable[[Any, int], str]] = None,
        max_manual_in: Optional[Callable[[], int]] = None,
    ) -> None:
        self._get_join_path = get_join_path
        self._join_predicates = join_predicates
        self._severity_predicate_for_alias = severity_predicate_for_alias
        self._effective_filter_mode = effective_filter_mode
        self._max_manual_in = max_manual_in or (lambda: QF_MAX_MANUAL_IN)

    def compile(
        self,
        *,
        node: Any,
        context: CompilationContext,
        qf_using_prep: bool,
        qf_base_alias: str,
        alias_by_wt: Dict[int, str],
        plan: Any,  # DomainPlan | None
        new_param: Callable[[Any], str],
        filter_mode_fn: Callable[[Any, int], str],
        force_exists_for_tables: Optional[set] = None,
        severity_table_ids: Optional[set] = None,
    ) -> Tuple[str, List[str]]:
        """Return (where_sql, exists_parts)."""
        if severity_table_ids is None:
            severity_table_ids = set()
        if not node:
            return "", []

        derived_by_exprid = context.derived_by_exprid
        derived_by_name = context.derived_by_name
        rewrite_by_colname = context.rewrite_by_colname
        rewrite_by_modelid = context.rewrite_by_modelid
        rewrite_by_wt_col = context.rewrite_by_wt_col

        exists_counter = 0

        def _normalize_in_values(value: Any) -> List[str]:
            if value is None:
                return []
            if isinstance(value, (list, tuple)):
                raw = list(value)
            elif isinstance(value, str):
                s = value.strip()
                if s.startswith("[") and s.endswith("]"):
                    parsed = None
                    try:
                        parsed = json.loads(s)
                    except JSON_LIST_PARSE_ERRORS:
                        try:
                            parsed = ast.literal_eval(s)
                        except LITERAL_LIST_PARSE_ERRORS:
                            parsed = None
                    if isinstance(parsed, (list, tuple)):
                        raw = list(parsed)
                    else:
                        raw = s.split(",")
                else:
                    raw = s.split(",")
            else:
                raw = [value]
            out: List[str] = []
            for item in raw:
                if item is None:
                    continue
                s = str(item).strip()
                if not s:
                    continue
                if len(s) >= 2 and s[0] == s[-1] and s[0] in ("'", '"'):
                    s = s[1:-1].strip()
                if s:
                    out.append(s)
            return out

        def compile_in_list(field_expr: str, values: List[Any], *, negate: bool = False) -> str:
            if not values:
                return ""
            if len(values) > self._max_manual_in():
                raise ForgeError(
                    "Too many IN values; upload a list/value_override instead",
                    status_code=400,
                )
            in_op = "NOT IN" if negate else "IN"
            expr = f"{field_expr} {in_op} ({', '.join(new_param(v) for v in values)})"
            if len(values) > 200:
                expr = f"{expr} -- normalized large IN list ({len(values)} items)"
            return expr

        def _field_name(field_ref: Any) -> str:
            if isinstance(field_ref, str):
                return field_ref.strip().lower().split(".")[-1]
            if isinstance(field_ref, dict):
                return str(field_ref.get("columnName") or "").strip().lower()
            return ""

        def _is_person_name_field(field_ref: Any) -> bool:
            col = _field_name(field_ref)
            if col == "" or "name" not in col:
                return False
            if any(token in col for token in ("county", "district", "school", "city", "state", "country")):
                return False
            return True

        def compile_condition_expr(field_expr: str, op: str, value: Any, *, field_ref: Any = None) -> str:
            op_norm = str(op or "").strip().lower()
            if op_norm in {"equals", "=", "==", "eq"}:
                if value is None:
                    return f"{field_expr} IS NULL"
                if isinstance(value, str):
                    if _is_person_name_field(field_ref):
                        return f"LOWER({field_expr}) LIKE LOWER({new_param(f'%{value}%')})"
                    return f"LOWER({field_expr}) = LOWER({new_param(value)})"
                return f"{field_expr} = {new_param(value)}"
            if op_norm in {"not_equals", "!=", "<>", "ne", "not_equal"}:
                if value is None:
                    return f"{field_expr} IS NOT NULL"
                if isinstance(value, str):
                    if _is_person_name_field(field_ref):
                        return f"LOWER({field_expr}) NOT LIKE LOWER({new_param(f'%{value}%')})"
                    return f"LOWER({field_expr}) <> LOWER({new_param(value)})"
                return f"{field_expr} <> {new_param(value)}"
            if op_norm in {"contains", "like"}:
                if isinstance(value, str):
                    return f"LOWER({field_expr}) LIKE LOWER({new_param(f'%{value}%')})"
                return f"{field_expr} LIKE {new_param(f'%{value}%')}"
            if op_norm in {"starts_with", "startswith", "prefix"}:
                if isinstance(value, str):
                    return f"LOWER({field_expr}) LIKE LOWER({new_param(f'{value}%')})"
                return f"{field_expr} LIKE {new_param(f'{value}%')}"
            if op_norm in {"gt", ">"}:
                return f"{field_expr} > {new_param(value)}"
            if op_norm in {"gte", ">="}:
                return f"{field_expr} >= {new_param(value)}"
            if op_norm in {"lt", "<"}:
                return f"{field_expr} < {new_param(value)}"
            if op_norm in {"lte", "<="}:
                return f"{field_expr} <= {new_param(value)}"
            if op_norm in {"in", "not_in", "not in"}:
                negate = op_norm in {"not_in", "not in"}
                if isinstance(value, dict) and value.get("mode"):
                    mode = value.get("mode")
                    if mode == "manual":
                        vals = _normalize_in_values(value.get("values"))
                        return compile_in_list(field_expr, vals, negate=negate)
                    if mode == "cohort":
                        raise ForgeError("cohort functionality is no longer supported", status_code=400)
                    if mode == "value_override":
                        list_type = value.get("listType")
                        list_id = value.get("listId")
                        if not list_type or list_type not in VALUE_OVERRIDE_IN_COLUMN_BY_TYPE:
                            raise ForgeError("Invalid value_override listType for IN filter", status_code=400)
                        if not list_id:
                            raise ForgeError("value_override IN requires listId", status_code=400)
                        table = TABLE_BY_TYPE.get(list_type)
                        if not table:
                            raise ForgeError("Invalid value_override listType for IN filter", status_code=400)
                        col_name = VALUE_OVERRIDE_IN_COLUMN_BY_TYPE[list_type]
                        # Build safe table reference
                        parts = [p.strip() for p in table.split(".") if p.strip()]
                        table_sql = ".".join(f"`{safe_ident(p)}`" for p in parts)
                        in_op = "NOT IN" if negate else "IN"
                        return (
                            f"{field_expr} {in_op} (SELECT {safe_ident(col_name)} "
                            f"FROM {table_sql} WHERE list_id = {new_param(list_id)})"
                        )
                    raise ForgeError("Unsupported IN mode", status_code=400)
                vals = _normalize_in_values(value)
                return compile_in_list(field_expr, vals, negate=negate)
            if op_norm == "between":
                if not isinstance(value, list) or len(value) != 2:
                    raise ForgeError("between requires [min,max]", status_code=400)
                return f"{field_expr} BETWEEN {new_param(value[0])} AND {new_param(value[1])}"
            if op_norm in {"is_null", "is null", "not_exists"}:
                return f"{field_expr} IS NULL"
            if op_norm in {"is_not_null", "is not null", "exists"}:
                return f"{field_expr} IS NOT NULL"
            raise ForgeError(f"Unsupported filter op: {op}", status_code=400)

        def field_expr_for_exists(field: Any, sub_alias: str) -> str:
            if isinstance(field, str):
                cn = field.strip()
            elif isinstance(field, dict):
                cn = (field.get("columnName") or "").strip()
            else:
                cn = ""
            if not cn or "." in cn:
                raise ForgeError("Invalid columnName for exists filter", status_code=400)
            return f"{safe_ident(sub_alias)}.{safe_ident(cn)}"

        def render_exists(group_key: str, group_info: Dict[str, Any]) -> str:
            nonlocal exists_counter
            exists_counter += 1

            if plan is None:
                raise ForgeError("EXISTS filters require a domain plan", status_code=400)
            if not self._get_join_path or not self._join_predicates or not self._severity_predicate_for_alias:
                raise ForgeError(
                    "EXISTS filter rendering requires join-resolution callbacks",
                    status_code=500,
                )

            sub_alias = f"e{exists_counter}"
            target_id = int(group_info["workspace_table_id"])
            path = self._get_join_path(plan, target_id)
            tables_by_id = {t.workspace_table_id: t for t in plan.tables}
            if not path:
                raise ForgeError("EXISTS requires non-primary table", status_code=400)

            first_edge = path[0]
            first_to = int(first_edge.to_workspace_table_id)
            from_alias = plan.primary.alias
            to_alias = sub_alias

            first_table = tables_by_id.get(first_to)
            if not first_table:
                raise ForgeError("Join path invalid for EXISTS", status_code=400)

            join_clauses = [f"{first_table.full_name} {safe_ident(to_alias)}"]

            where_preds: List[str] = []
            where_preds.extend(self._join_predicates(first_edge, from_alias, to_alias))
            first_severity_pred = self._severity_predicate_for_alias(
                alias=safe_ident(to_alias),
                workspace_table_id=first_to,
                severity_table_ids=severity_table_ids,
            )
            if first_severity_pred:
                where_preds.append(first_severity_pred)

            current_alias = to_alias
            current_id = first_to

            for edge in path[1:]:
                if int(edge.from_workspace_table_id) != int(current_id):
                    raise ForgeError("Join path invalid for EXISTS", status_code=400)
                next_id = int(edge.to_workspace_table_id)
                next_table = tables_by_id.get(next_id)
                if not next_table:
                    raise ForgeError("Join path invalid for EXISTS", status_code=400)
                next_alias = f"{sub_alias}_{next_id}"
                join_preds = self._join_predicates(edge, current_alias, next_alias)
                next_severity_pred = self._severity_predicate_for_alias(
                    alias=safe_ident(next_alias),
                    workspace_table_id=next_id,
                    severity_table_ids=severity_table_ids,
                )
                if next_severity_pred:
                    join_preds.append(next_severity_pred)
                join_clauses.append(
                    f"JOIN {next_table.full_name} {safe_ident(next_alias)} "
                    f"ON {' AND '.join(join_preds)}"
                )
                current_alias = next_alias
                current_id = next_id

            pred_sqls = []
            for cond in group_info["predicates"]:
                field_expr = field_expr_for_exists(cond["field"], current_alias)
                pred_sqls.append(
                    compile_condition_expr(
                        field_expr,
                        cond["op"],
                        cond["value"],
                        field_ref=cond.get("field"),
                    )
                )

            all_where = [p for p in where_preds + pred_sqls if p]
            if not all_where:
                raise ForgeError("EXISTS predicates missing", status_code=400)

            subquery = (
                "SELECT 1\n"
                f"FROM {' '.join(join_clauses)}\n"
                f"WHERE {' AND '.join(all_where)}"
            )
            return f"EXISTS (\n{subquery}\n)"

        def walk(n: Any) -> Tuple[str, Dict[str, Any]]:
            if not isinstance(n, dict):
                raise ForgeError("Invalid filter node", status_code=400)

            t = n.get("type")

            if t == "group":
                match = (n.get("match") or "and").lower()
                children = n.get("children") or []
                if match == "and":
                    where_parts: List[str] = []
                    exists_groups: Dict[str, Any] = {}
                    for c in children:
                        w_sql, ex = walk(c)
                        if w_sql:
                            where_parts.append(w_sql)
                        for k, v in ex.items():
                            if k not in exists_groups:
                                exists_groups[k] = v
                            else:
                                if exists_groups[k]["workspace_table_id"] != v["workspace_table_id"]:
                                    raise ForgeError("existsScopeId must not mix tables", status_code=400)
                                exists_groups[k]["predicates"].extend(v["predicates"])
                    where_sql = " AND ".join([f"({p})" if " OR " in p else p for p in where_parts])
                    return where_sql, exists_groups

                parts: List[str] = []
                for c in children:
                    w_sql, ex = walk(c)
                    if ex:
                        exists_parts_inner = [render_exists(k, v) for k, v in ex.items()]
                        expr_parts = [p for p in ([w_sql] if w_sql else []) + exists_parts_inner if p]
                        parts.append(" AND ".join(expr_parts))
                    elif w_sql:
                        parts.append(w_sql)
                if not parts:
                    return "", {}
                return f"({' OR '.join(parts)})", {}

            if t == "condition":
                field = n.get("field")
                is_virtual_expr = isinstance(field, dict) and bool(field.get("exprId"))

                wt_id = None
                if isinstance(field, dict):
                    wt_id = field.get("workspaceTableId")
                if wt_id is None:
                    if plan is not None:
                        wt_id = plan.primary.workspace_table_id
                    else:
                        wt_id = 0

                if is_virtual_expr:
                    filter_mode = "WHERE"
                elif self._effective_filter_mode is not None:
                    filter_mode = self._effective_filter_mode(plan, int(wt_id))
                else:
                    filter_mode = filter_mode_fn(plan, int(wt_id))
                if (
                    not is_virtual_expr
                    and force_exists_for_tables
                    and wt_id is not None
                    and int(wt_id) in force_exists_for_tables
                ):
                    filter_mode = "EXISTS"
                if is_virtual_expr and filter_mode == "EXISTS":
                    raise ForgeError("Virtual expr fields cannot be EXISTS filters", status_code=500)

                op = n.get("op")
                value = n.get("value")

                if filter_mode == "WHERE":
                    if isinstance(field, str):
                        if "." in field:
                            raise ForgeError(
                                f"Qualified column names are not allowed in filters: {field}",
                                status_code=400,
                            )
                        if qf_using_prep and field in rewrite_by_colname:
                            field_expr = rewrite_by_colname[field]
                        else:
                            field_expr = physical_col_expr(
                                field, qf_using_prep=qf_using_prep, qf_base_alias=qf_base_alias, alias=None
                            )
                    else:
                        field_expr = col_expr(
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
                    return compile_condition_expr(field_expr, op, value, field_ref=field), {}

                if filter_mode == "EXISTS":
                    key = n.get("existsScopeId") or str(wt_id)
                    return "", {
                        str(key): {
                            "workspace_table_id": int(wt_id),
                            "predicates": [{"field": field, "op": op, "value": value}],
                        }
                    }

                raise ForgeError("Invalid filter mode", status_code=400)

            raise ForgeError("Invalid filter node type", status_code=400)

        where_sql, exists_groups = walk(node)
        exists_parts_out = [render_exists(k, v) for k, v in exists_groups.items()]
        return where_sql, exists_parts_out
