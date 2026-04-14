# app/services/query_forge_service.py
from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple, Union

from app.exceptions.forge_error import ForgeError
from app.ports.sql_executor import ForgeQueryPort
from app.services.domain_resolver import DomainPlan, DomainResolver
from app.services.sqljson import validate_and_normalize_derived_sqljson
from app.services.value_overrides.list_schema import TABLE_BY_TYPE

QF_MAX_MANUAL_IN = 150
GLOBAL_ROW_QUALITY_COLUMN = "tdoe_severity_code"
GLOBAL_ROW_QUALITY_MAX_EXCLUSIVE = 4

VALUE_OVERRIDE_IN_COLUMN_BY_TYPE = {
    "regions": "zipcode",
    "npiCategories": "npi",
    "serviceLines": "procedure_code",
}

VALUE_OVERRIDE_KEY_BY_TYPE = {
    "regions": "zipcode",
    "npiCategories": "npi",
    "serviceLines": "procedure_code",
}

VALUE_OVERRIDE_JOIN_ALIAS_BY_TYPE = {
    "regions": "cw_regions",
    "npiCategories": "cw_npi",
    "serviceLines": "cw_sl",
}

VALUE_OVERRIDE_FIELDS_BY_TYPE = {
    "regions": ["region", "subregion"],
    "npiCategories": ["npi_type_code", "customer_npi_category_1", "customer_npi_category_2"],
    "serviceLines": ["customer_service_line", "customer_sub_service_line"],
}

VALUE_OVERRIDE_PROJECT_ALIASES_BY_TYPE = {
    "regions": {
        "region": "cw_region",
        "subregion": "cw_subregion",
    },
    "npiCategories": {
        "npi_type_code": "cw_npi_type_code",
        "customer_npi_category_1": "cw_npi_category_1",
        "customer_npi_category_2": "cw_npi_category_2",
    },
    "serviceLines": {
        "customer_service_line": "cw_service_line",
        "customer_sub_service_line": "cw_sub_service_line",
    },
}


@dataclass(frozen=True)
class ForgeCompiledQuery:
    sql: str
    qf_count_sql: str
    params: Dict[str, Any]
    qf_output_cols: List[Dict[str, Any]]


@dataclass(frozen=True)
class QueryForgeRunResult:
    sql: str
    qf_rendered_sql: str
    params: Dict[str, Any]
    rows: List[Any]
    columns: List[Dict[str, Any]]
    total: int
    limit: int
    offset: int


@dataclass(frozen=True)
class QueryForgePreparedQuery:
    sql: str
    qf_rendered_sql: str
    params: Dict[str, Any]
    qf_count_sql: str
    columns: List[Dict[str, Any]]
    limit: int
    offset: int


QfColumnKey = Union[str, Dict[str, Any]]  # legacy strings + new {workspaceTableId?,modelColumnId,columnName,exprId?}


class QueryForgeService:
    """
    Notes on safety / correctness:

    - We NEVER trust client-supplied table qualifiers (e.g. "t.col", "schema.t.col").
      The only authoritative FROM is DomainResolver.resolve(domainId).full_name.

    - We alias the base FROM as the primary table alias and compile physical columns as <alias>.<col>.

    - DataPrep compiles into a CTE `prep` which selects explicit base columns plus derived outputs.
      Subsequent SELECTs use `FROM prep`.

    - ✅ Important: DataPrep outputs use INTERNAL identifiers (e.g. __dp_claim_type) to avoid
      collisions with base columns inside the CTE. Query-wide references are rewritten
      to these internal identifiers, and projection aliases back to the user-visible name.
    """

    def __init__(self, executor: ForgeQueryPort, domain_resolver: DomainResolver):
        self._executor = executor
        self._domains = domain_resolver

    def run(
        self,
        raw_query: Dict[str, Any],
        mode: str = "preview",
        limit: int = 200,
        offset: int = 0,
    ) -> QueryForgeRunResult:
        normalized = self.normalize(raw_query)
        compiled = self.compile(normalized, mode=mode, limit=limit, offset=offset)

        data = self._executor.submit_statement(compiled.sql, parameters=compiled.params)
        qf_result_rows = (data or {}).get("rows") or []

        count = self._executor.submit_statement(compiled.qf_count_sql, parameters=compiled.params)
        total = self._qf_extract_total((count or {}).get("rows") or [])

        columns = (
            self._qf_infer_cols(qf_result_rows)
            or compiled.qf_output_cols
            or self._qf_cols_from_json(normalized)
        )
        rows = self._qf_rows_to_dicts(qf_result_rows, columns)

        rendered_sql = self._qf_render_sql(compiled.sql, compiled.params)

        return QueryForgeRunResult(
            sql=compiled.sql,
            qf_rendered_sql=rendered_sql,
            params=compiled.params,
            rows=rows,
            columns=columns,
            total=total,
            limit=limit,
            offset=offset,
        )

    def prepare(
        self,
        raw_query: Dict[str, Any],
        mode: str = "preview",
        limit: int = 200,
        offset: int = 0,
    ) -> QueryForgePreparedQuery:
        normalized = self.normalize(raw_query)
        compiled = self.compile(normalized, mode=mode, limit=limit, offset=offset)
        columns = compiled.qf_output_cols or self._qf_cols_from_json(normalized)
        rendered_sql = self._qf_render_sql(compiled.sql, compiled.params)
        return QueryForgePreparedQuery(
            sql=compiled.sql,
            qf_rendered_sql=rendered_sql,
            params=compiled.params,
            qf_count_sql=compiled.qf_count_sql,
            columns=columns,
            limit=limit,
            offset=offset,
        )

    # -----------------------------
    # Normalize / validate
    # -----------------------------
    def _qf_norm_filters(self, node: Any) -> Any:
        if not isinstance(node, dict):
            return node

        node_type = node.get("type")
        if node_type != "group":
            return node

        match = (node.get("match") or "and").lower()
        children = [self._qf_norm_filters(c) for c in (node.get("children") or [])]
        node = {**node, "children": children}

        if match != "or" or not children:
            return node

        first = children[0]
        if not isinstance(first, dict) or first.get("type") != "condition" or first.get("op") != "equals":
            return node

        def field_key(field: Any) -> tuple:
            if isinstance(field, dict):
                return (
                    field.get("workspaceTableId"),
                    field.get("modelColumnId"),
                    field.get("columnName"),
                    field.get("exprId"),
                    field.get("alias"),
                )
            return ("__str__", field)

        key = field_key(first.get("field"))
        values: List[Any] = []
        for child in children:
            if not isinstance(child, dict):
                return node
            if child.get("type") != "condition" or child.get("op") != "equals":
                return node
            if field_key(child.get("field")) != key:
                return node
            values.append(child.get("value"))

        collapsed: Dict[str, Any] = {
            "type": "condition",
            "op": "in",
            "field": first.get("field"),
            "value": values,
        }
        if node.get("id"):
            collapsed["id"] = node.get("id")
        return collapsed

    def normalize(self, q: Dict[str, Any]) -> Dict[str, Any]:
        if not q or not isinstance(q, dict):
            raise ForgeError("Missing query", status_code=400)

        q = dict(q)
        q, _, _ = validate_and_normalize_derived_sqljson(q, strict=True)

        q.setdefault("version", 1)
        q.setdefault("domainId", None)
        q.setdefault("columns", [])
        q.setdefault("dataPrep", None)
        q.setdefault("filters", None)
        q.setdefault("aggs", {"enabled": False, "metrics": [], "groupBy": []})
        q.setdefault("sorting", [])
        q.setdefault("distinct", False)
        q.setdefault("value_overrideAttachments", [])
        q.setdefault("value_overrides", [])
        q.setdefault("meta", {})

        if q.get("domainId") is None:
            raise ForgeError("domainId is required", status_code=400)

        distinct = q.get("distinct", False)
        if not isinstance(distinct, bool):
            raise ForgeError("distinct must be a boolean", status_code=400)
        q["distinct"] = distinct

        cols = q.get("columns") or []
        if not isinstance(cols, list):
            raise ForgeError("columns must be a list", status_code=400)

        norm_cols: List[Dict[str, Any]] = []
        for i, c in enumerate(cols):
            if not isinstance(c, dict):
                raise ForgeError(f"columns[{i}] must be an object", status_code=400)

            col_source: Any = c
            if "columnName" not in c:
                if "field" in c:
                    if not isinstance(c.get("field"), dict):
                        raise ForgeError(f"columns[{i}].field must be an object", status_code=400)
                    col_source = c.get("field")
                elif "col" in c:
                    if not isinstance(c.get("col"), dict):
                        raise ForgeError(f"columns[{i}].col must be an object", status_code=400)
                    col_source = c.get("col")

            norm_col = self._qf_norm_col_key(col_source, path=f"columns[{i}]")
            col_name = norm_col.get("columnName")

            alias = c.get("alias")
            if alias is None and isinstance(col_source, dict):
                alias = col_source.get("alias")
            if alias is not None and not isinstance(alias, str):
                raise ForgeError(f"columns[{i}].alias must be a string or null", status_code=400)
            alias = (alias or "").strip() or None

            norm_cols.append(
                {
                    "workspaceTableId": norm_col.get("workspaceTableId"),
                    "modelColumnId": norm_col.get("modelColumnId"),
                    "columnName": col_name,
                    "exprId": norm_col.get("exprId"),
                    "modelTableId": c.get("modelTableId")
                    if "modelTableId" in c
                    else (col_source.get("modelTableId") if isinstance(col_source, dict) else None),
                    "modelTableName": c.get("modelTableName")
                    if "modelTableName" in c
                    else (col_source.get("modelTableName") if isinstance(col_source, dict) else None),
                    "fullName": c.get("fullName")
                    if "fullName" in c
                    else (col_source.get("fullName") if isinstance(col_source, dict) else None),
                    "dataType": c.get("dataType")
                    if "dataType" in c
                    else (col_source.get("dataType") if isinstance(col_source, dict) else None),
                    "nullable": c.get("nullable")
                    if "nullable" in c
                    else (col_source.get("nullable") if isinstance(col_source, dict) else None),
                    "alias": alias,
                }
            )
        q["columns"] = norm_cols

        aggs = q.get("aggs")
        if aggs is None:
            aggs = {"enabled": False, "metrics": [], "groupBy": []}
        if not isinstance(aggs, dict):
            raise ForgeError("aggs must be an object", status_code=400)

        aggs.setdefault("enabled", False)
        aggs.setdefault("metrics", [])
        aggs.setdefault("groupBy", [])

        gb = aggs.get("groupBy") or []
        if not isinstance(gb, list):
            raise ForgeError("aggs.groupBy must be a list", status_code=400)

        norm_gb: List[Dict[str, Any]] = []
        for j, g in enumerate(gb):
            norm_gb.append(self._qf_norm_col_key(g, path=f"aggs.groupBy[{j}]"))
        aggs["groupBy"] = norm_gb

        metrics = aggs.get("metrics") or []
        if not isinstance(metrics, list):
            raise ForgeError("aggs.metrics must be a list", status_code=400)

        norm_metrics: List[Dict[str, Any]] = []
        for i, m in enumerate(metrics):
            if not isinstance(m, dict):
                raise ForgeError(f"aggs.metrics[{i}] must be an object", status_code=400)

            metric_ref = m.get("metricRef")
            if metric_ref is None:
                metric_ref = m.get("metric_ref")

            field = m.get("field", None)
            if field is None and "column" in m:
                field = m.get("column")
            fn_input = str(m.get("fn") or m.get("agg") or "").strip()
            label = m.get("label")

            if isinstance(metric_ref, dict):
                if field is None:
                    field = (
                        metric_ref.get("field")
                        or metric_ref.get("column")
                        or metric_ref.get("columnKey")
                        or metric_ref.get("column_key")
                    )
                if fn_input == "":
                    fn_input = str(metric_ref.get("fn") or metric_ref.get("agg") or "").strip()
                if label is None:
                    label = metric_ref.get("label")

            fn_field = self._extract_metric_field_from_fn_token(fn_input)
            if field is None and fn_field is not None:
                field = fn_field
            if fn_input == "" and field is not None:
                fn_input = "count"
            fn = self._normalize_metric_fn_token(fn_input)
            if fn == "":
                raise ForgeError(f"aggs.metrics[{i}].fn is required", status_code=400)

            expr = None

            norm_field = None
            if fn == "expr":
                expr = self._qf_norm_metric_expr(m.get("expr"), path=f"aggs.metrics[{i}].expr")
            elif field is not None:
                # COUNT(*) is valid and may arrive as an empty field object from planner adapters.
                if fn == "count" and self._is_empty_count_metric_field(field):
                    norm_field = None
                else:
                    norm_field = self._qf_norm_col_key(field, path=f"aggs.metrics[{i}].field")

            if label is not None and not isinstance(label, str):
                raise ForgeError(f"aggs.metrics[{i}].label must be string or null", status_code=400)
            label = (label or "").strip() or None

            mid = m.get("id") or None
            if mid is not None and not isinstance(mid, str):
                raise ForgeError(f"aggs.metrics[{i}].id must be string", status_code=400)

            metric_row: Dict[str, Any] = {"id": mid or f"m{i+1}", "fn": fn, "field": norm_field, "label": label}
            if expr is not None:
                metric_row["expr"] = expr
            norm_metrics.append(metric_row)
        aggs["metrics"] = norm_metrics
        q["aggs"] = aggs

        sorting = q.get("sorting") or []
        if not isinstance(sorting, list):
            raise ForgeError("sorting must be a list", status_code=400)

        norm_sort: List[Dict[str, Any]] = []
        for i, s in enumerate(sorting):
            if not isinstance(s, dict):
                raise ForgeError(f"sorting[{i}] must be an object", status_code=400)

            metric_ref = str(s.get("metricRef") or s.get("metric_ref") or "").strip()
            if "col" in s:
                col = self._qf_norm_col_key(s.get("col"), path=f"sorting[{i}].col")
            elif "columnName" in s:
                col = self._qf_norm_col_key(s.get("columnName"), path=f"sorting[{i}].columnName")
            elif metric_ref:
                col = None
            else:
                raise ForgeError(f"sorting[{i}] requires col, columnName, or metricRef", status_code=400)

            dir_ = (s.get("dir") or "asc").lower()
            if dir_ not in ("asc", "desc"):
                raise ForgeError(f"sorting[{i}].dir must be asc|desc", status_code=400)

            if metric_ref:
                norm_sort.append({"metricRef": metric_ref.lower(), "dir": dir_})
            else:
                norm_sort.append({"col": col, "dir": dir_})
        q["sorting"] = norm_sort

        if q.get("filters") is None:
            q["filters"] = None

        dp = q.get("dataPrep")
        if dp is not None:
            if not isinstance(dp, dict):
                raise ForgeError("dataPrep must be an object or null", status_code=400)
            dp.setdefault("enabled", bool((dp.get("rules") or [])))
            dp.setdefault("rules", [])
            if not isinstance(dp.get("rules"), list):
                raise ForgeError("dataPrep.rules must be a list", status_code=400)
        q["dataPrep"] = dp

        if (not q.get("columns")) and not bool(q.get("aggs", {}).get("enabled")):
            raise ForgeError("Select at least one column (or enable aggregations).", status_code=400)

        def norm_value_override_attachment(cw: Any, idx: int) -> Dict[str, Any]:
            if not isinstance(cw, dict):
                raise ForgeError(f"value_overrideAttachments[{idx}] must be an object", status_code=400)

            list_type = cw.get("listType") or cw.get("type")
            if not list_type or list_type not in VALUE_OVERRIDE_KEY_BY_TYPE:
                raise ForgeError("Invalid value_override listType", status_code=400)

            list_id = cw.get("listId")
            if not list_id or not isinstance(list_id, str):
                raise ForgeError("value_override listId is required", status_code=400)

            mode = (cw.get("mode") or "filter").strip().lower()
            if mode not in ("filter", "join"):
                raise ForgeError("value_override mode must be filter or join", status_code=400)

            raw_cols = cw.get("domainJoinColumns")
            if raw_cols is None:
                raw_col = cw.get("domainJoinColumn")
                raw_cols = [raw_col] if raw_col is not None else []
            if not isinstance(raw_cols, list):
                raise ForgeError("domainJoinColumns must be a list", status_code=400)

            norm_cols = [
                self._qf_norm_col_key(col, path=f"value_overrideAttachments[{idx}].domainJoinColumns[{j}]")
                for j, col in enumerate(raw_cols)
            ]

            value_override_join_cols = cw.get("value_overrideJoinColumns")
            if value_override_join_cols is None:
                value_override_join_cols = [VALUE_OVERRIDE_KEY_BY_TYPE[list_type]]
            if not isinstance(value_override_join_cols, list):
                raise ForgeError("value_overrideJoinColumns must be a list", status_code=400)

            project_fields = cw.get("projectFields") or []
            if not isinstance(project_fields, list):
                raise ForgeError("projectFields must be a list", status_code=400)

            return {
                "id": (cw.get("id") if isinstance(cw.get("id"), str) else None),
                "listType": list_type,
                "listId": str(list_id),
                "mode": mode,
                "domainJoinColumns": norm_cols,
                "value_overrideJoinColumns": value_override_join_cols,
                "projectFields": project_fields,
                "supportsSeparateAliasJoins": bool(
                    cw.get("supportsSeparateAliasJoins") or cw.get("separateAliasJoins")
                ),
            }

        def as_attachment_list(raw: Any) -> List[Any]:
            if raw is None:
                return []
            if isinstance(raw, list):
                return raw
            if isinstance(raw, dict):
                return [v for v in raw.values() if v]
            raise ForgeError("value_overrides must be a list or object", status_code=400)

        raw_value_override_attachments = q.get("value_overrideAttachments")
        if not raw_value_override_attachments:
            raw_value_override_attachments = q.get("value_overrides")
        q["value_overrideAttachments"] = [
            norm_value_override_attachment(cw, idx) for idx, cw in enumerate(as_attachment_list(raw_value_override_attachments))
        ]

        raw_cohort_attachment = q.get("cohortAttachment")
        if not raw_cohort_attachment:
            raw_cohort_attachment = q.get("cohortJoin")
        if raw_cohort_attachment is None:
            q["cohortAttachment"] = None
        else:
            raise ForgeError("cohort functionality is no longer supported", status_code=400)

        return q

    @staticmethod
    def _normalize_metric_fn_token(raw: Any) -> str:
        token = str(raw or "").strip().lower()
        if token == "":
            return ""
        fn_match = re.match(
            r"^(count\s+distinct|count_distinct|countdistinct|count|sum|avg|min|max)\s*\((.*?)\)$",
            token,
            flags=re.IGNORECASE,
        )
        if fn_match:
            token = str(fn_match.group(1) or "").strip().lower()
        token = token.replace("-", "_").replace(" ", "_")
        if token in {"countdistinct", "count_distinct"}:
            return "count_distinct"
        if token in {"count", "sum", "avg", "min", "max", "expr"}:
            return token
        return token

    @staticmethod
    def _extract_metric_field_from_fn_token(raw: Any) -> Optional[Dict[str, Any]]:
        token = str(raw or "").strip()
        if token == "":
            return None
        fn_match = re.match(
            r"^(count\s+distinct|count_distinct|countdistinct|count|sum|avg|min|max)\s*\((.*?)\)$",
            token,
            flags=re.IGNORECASE,
        )
        if fn_match is None:
            return None
        field_token = str(fn_match.group(2) or "").strip()
        if field_token == "" or field_token == "*":
            return None
        return {
            "modelColumnId": None,
            "columnName": field_token,
            "exprId": None,
        }

    @staticmethod
    def _is_empty_count_metric_field(field: Any) -> bool:
        if field is None:
            return True
        if isinstance(field, dict):
            column_name = field.get("columnName")
            expr_id = field.get("exprId")
            model_column_id = field.get("modelColumnId")
            workspace_table_id = field.get("workspaceTableId")
            if isinstance(column_name, str) and column_name.strip():
                return False
            return not any(
                value not in (None, "")
                for value in (expr_id, model_column_id, workspace_table_id)
            )
        return False

    def _qf_norm_col_key(self, v: Any, path: str) -> Dict[str, Any]:
        if isinstance(v, str):
            s = v.strip()
            if not s:
                raise ForgeError(f"{path} is required", status_code=400)
            if "." in s:
                raise ForgeError(f"{path} must be an unqualified column name (no dots): {s}", status_code=400)
            return {"modelColumnId": None, "columnName": s, "exprId": None}

        if not isinstance(v, dict):
            raise ForgeError(f"{path} must be a column key", status_code=400)

        cn = v.get("columnName")
        if not cn or not isinstance(cn, str):
            raise ForgeError(f"{path}.columnName is required", status_code=400)
        if "." in cn:
            raise ForgeError(f"{path}.columnName must be unqualified (no dots): {cn}", status_code=400)

        mid = v.get("modelColumnId", None)
        if mid is not None and not isinstance(mid, int):
            raise ForgeError(f"{path}.modelColumnId must be number or null", status_code=400)

        expr = v.get("exprId", None)
        if expr is not None and not isinstance(expr, str):
            raise ForgeError(f"{path}.exprId must be string or null", status_code=400)

        wt_id = v.get("workspaceTableId", None)
        if wt_id is not None and not isinstance(wt_id, int):
            raise ForgeError(f"{path}.workspaceTableId must be number or null", status_code=400)

        return {"workspaceTableId": wt_id, "modelColumnId": mid, "columnName": cn, "exprId": expr}

    def _qf_norm_metric_expr(self, expr: Any, path: str) -> Dict[str, Any]:
        if not isinstance(expr, dict):
            raise ForgeError(f"{path} must be an object", status_code=400)
        kind = str(expr.get("kind") or "").strip().lower()
        if kind != "ratio":
            raise ForgeError(f"{path}.kind must be ratio", status_code=400)

        numerator = expr.get("numerator")
        denominator = expr.get("denominator")
        if not isinstance(numerator, dict):
            raise ForgeError(f"{path}.numerator must be an object", status_code=400)
        if not isinstance(denominator, dict):
            raise ForgeError(f"{path}.denominator must be an object", status_code=400)

        def _norm_part(part: Dict[str, Any], part_path: str) -> Dict[str, Any]:
            fn = str(part.get("fn") or part.get("agg") or "").strip().lower().replace("-", "_")
            if fn == "countdistinct":
                fn = "count_distinct"
            if fn not in {"count", "count_distinct", "sum", "avg", "min", "max"}:
                raise ForgeError(f"{part_path}.fn is invalid", status_code=400)
            field = part.get("field")
            if field is None:
                field = part.get("columnKey") or part.get("column_key")
                if isinstance(field, str):
                    m = re.match(r"^wt(\d+)\.([A-Za-z_][A-Za-z0-9_]*)$", field.strip())
                    if m:
                        field = {"workspaceTableId": int(m.group(1)), "columnName": m.group(2)}
            if field is None:
                if fn != "count":
                    raise ForgeError(f"{part_path}.field is required", status_code=400)
                norm_field = None
            else:
                norm_field = self._qf_norm_col_key(field, path=f"{part_path}.field")
            filters = part.get("filters")
            if filters is not None and not isinstance(filters, dict):
                raise ForgeError(f"{part_path}.filters must be an object", status_code=400)
            return {"fn": fn, "field": norm_field, "filters": filters}

        multiply_by = expr.get("multiply_by", expr.get("multiplyBy"))
        if multiply_by is not None and not isinstance(multiply_by, (int, float)):
            raise ForgeError(f"{path}.multiplyBy must be numeric or null", status_code=400)

        return {
            "kind": "ratio",
            "name": (str(expr.get("name") or "").strip() or None),
            "numerator": _norm_part(numerator, f"{path}.numerator"),
            "denominator": _norm_part(denominator, f"{path}.denominator"),
            "safe_divide": bool(expr.get("safe_divide", expr.get("safeDivide", True))),
            "multiply_by": float(multiply_by) if isinstance(multiply_by, (int, float)) else None,
        }

    def _qf_attach_table_ids(
        self,
        value_override_attachments: List[Any],
        cohort_attachment: Optional[Dict[str, Any]],
        primary_id: int,
    ) -> set[int]:
        needed: set[int] = set()

        for i, cw in enumerate(value_override_attachments or []):
            if not isinstance(cw, dict):
                raise ForgeError("value_overrideAttachments entries must be objects", status_code=400)
            cols = cw.get("domainJoinColumns") or []
            if not isinstance(cols, list):
                raise ForgeError(f"value_overrideAttachments[{i}].domainJoinColumns must be a list", status_code=400)
            for j, col in enumerate(cols):
                norm = self._qf_norm_col_key(col, f"value_overrideAttachments[{i}].domainJoinColumns[{j}]")
                wt_id = norm.get("workspaceTableId") or primary_id
                needed.add(int(wt_id))

        if cohort_attachment:
            if not isinstance(cohort_attachment, dict):
                raise ForgeError("cohortAttachment must be an object", status_code=400)
            col = cohort_attachment.get("domainJoinColumn")
            if col is not None:
                norm = self._qf_norm_col_key(col, "cohortAttachment.domainJoinColumn")
                wt_id = norm.get("workspaceTableId") or primary_id
                needed.add(int(wt_id))

        return needed

    # -----------------------------
    # Compile
    # -----------------------------
    _IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

    def _qf_supports_array_params(self) -> bool:
        if hasattr(self._executor, "supports_array_params"):
            return bool(getattr(self._executor, "supports_array_params"))
        return "databricks" in self._executor.__class__.__name__.lower()

    def _qf_filter_table_ids(self, node: Any, plan: DomainPlan) -> set[int]:
        ids: set[int] = set()

        def walk(n: Any) -> None:
            if not isinstance(n, dict):
                return
            t = n.get("type")
            if t == "group":
                for c in (n.get("children") or []):
                    walk(c)
                return
            if t != "condition":
                return

            field = n.get("field")
            if isinstance(field, dict) and field.get("exprId"):
                wt_id = plan.primary.workspace_table_id
            elif isinstance(field, dict):
                wt_id = field.get("workspaceTableId")
            else:
                wt_id = None

            if wt_id is None:
                wt_id = plan.primary.workspace_table_id
            try:
                wt_id_int = int(wt_id)
            except Exception:
                return
            if wt_id_int != 0:
                ids.add(wt_id_int)

        walk(node)
        return ids

    def _qf_sorting_table_ids(self, sorting: List[Dict[str, Any]], plan: DomainPlan) -> set[int]:
        ids: set[int] = set()
        for s in sorting:
            if not isinstance(s, dict):
                continue
            metric_ref = str(s.get("metricRef") or s.get("metric_ref") or "").strip()
            if metric_ref:
                ids.add(int(plan.primary.workspace_table_id))
                continue
            col = s.get("col") if "col" in s else s.get("columnName")
            if isinstance(col, dict):
                wt_id = col.get("workspaceTableId")
            else:
                wt_id = None
            if wt_id is None:
                wt_id = plan.primary.workspace_table_id
            try:
                wt_id_int = int(wt_id)
            except Exception:
                continue
            if wt_id_int != 0:
                ids.add(wt_id_int)
        return ids

    def _select_two_phase_key_column(
        self,
        *,
        q: Dict[str, Any],
        plan: DomainPlan,
        primary_id: int,
        filter_only_table_ids: set[int],
    ) -> Optional[str]:
        candidates: List[str] = []
        candidates.extend(
            self._primary_join_key_candidates(
                plan=plan,
                primary_id=primary_id,
                filter_only_table_ids=filter_only_table_ids,
            )
        )
        candidates.extend(
            self._primary_query_key_candidates(
                q=q,
                primary_id=primary_id,
            )
        )

        catalog = self._load_domain_column_catalog(plan)
        primary_columns = {
            col
            for (wt_id, col), _meta in catalog.items()
            if int(wt_id) == int(primary_id) and col
        }
        if primary_columns:
            preferred = [
                "patient_id",
                "k_person",
                "k_staff",
                "staff_unique_id",
                "local_staff_id",
                "k_student",
                "student_unique_id",
                "school_id",
                "id",
                "oid",
            ]
            for name in preferred:
                if name in primary_columns:
                    candidates.append(name)
            for name in sorted(primary_columns):
                if self._looks_like_identifier_column(name):
                    candidates.append(name)

        seen: set[str] = set()
        for raw in candidates:
            col = str(raw or "").strip().lower()
            if not col or col in seen:
                continue
            seen.add(col)
            if not self._looks_like_identifier_column(col):
                continue
            if primary_columns and col not in primary_columns:
                continue
            return col
        return None

    def _primary_join_key_candidates(
        self,
        *,
        plan: DomainPlan,
        primary_id: int,
        filter_only_table_ids: set[int],
    ) -> List[str]:
        out: List[str] = []
        for wt_id in sorted(filter_only_table_ids):
            try:
                path = self._domains.get_join_path(plan, int(wt_id))
            except Exception:
                continue
            for edge in path:
                if int(edge.from_workspace_table_id) != int(primary_id):
                    continue
                spec = edge.join_spec or {}
                on_list = spec.get("on") or []
                if not isinstance(on_list, list):
                    continue
                for item in on_list:
                    if not isinstance(item, dict):
                        continue
                    left = item.get("left") or {}
                    col = str((left.get("columnName") or left.get("col") or "")).strip().lower()
                    if col and "." not in col:
                        out.append(col)
        return out

    @staticmethod
    def _primary_query_key_candidates(*, q: Dict[str, Any], primary_id: int) -> List[str]:
        out: List[str] = []
        for c in list(q.get("columns") or []):
            if not isinstance(c, dict):
                continue
            cn = str(c.get("columnName") or "").strip().lower()
            wt = c.get("workspaceTableId")
            if not cn or "." in cn:
                continue
            try:
                wt_ok = wt is None or int(wt) == int(primary_id)
            except Exception:
                wt_ok = False
            if wt_ok:
                out.append(cn)

        for s in list(q.get("sorting") or []):
            if not isinstance(s, dict):
                continue
            col = s.get("col") if "col" in s else s.get("columnName")
            if not isinstance(col, dict):
                continue
            cn = str(col.get("columnName") or "").strip().lower()
            wt = col.get("workspaceTableId")
            if not cn or "." in cn:
                continue
            try:
                wt_ok = wt is None or int(wt) == int(primary_id)
            except Exception:
                wt_ok = False
            if wt_ok:
                out.append(cn)
        return out

    @staticmethod
    def _looks_like_identifier_column(column_name: str) -> bool:
        col = str(column_name or "").strip().lower()
        if not col:
            return False
        if col in {"id", "oid", "k_person", "k_staff", "k_student"}:
            return True
        if col.startswith("k_"):
            return True
        if col.endswith("_id") or col.endswith("_key"):
            return True
        if "unique_id" in col:
            return True
        return False

    def _load_domain_column_catalog(self, plan: DomainPlan) -> Dict[tuple[int, str], Dict[str, Any]]:
        ws_id = getattr(self._domains, "_workspace_id", None)
        sql = getattr(self._domains, "_sql", None)
        if not ws_id or sql is None or not hasattr(sql, "execute_query_mappings"):
            return {}
        table_ids = sorted({int(t.workspace_table_id) for t in (plan.tables or [])})
        if not table_ids:
            return {}
        in_clause = ", ".join(str(int(tid)) for tid in table_ids)
        sql_text = f"""
            SELECT
              wc.workspace_table_id,
              wc.column_name,
              LOWER(COALESCE(wc.data_type, '')) AS data_type
            FROM workspace_column wc
            JOIN workspace_table wt
              ON wt.id = wc.workspace_table_id
            WHERE wt.workspace_id = :ws
              AND wc.workspace_table_id IN ({in_clause})
        """
        rows = sql.execute_query_mappings(sql_text, {"ws": ws_id}) or []
        catalog: Dict[tuple[int, str], Dict[str, Any]] = {}
        for row in rows:
            try:
                wt_id = int(row.get("workspace_table_id"))
            except Exception:
                continue
            col_name = str(row.get("column_name") or "").strip().lower()
            if not col_name:
                continue
            catalog[(wt_id, col_name)] = {"data_type": str(row.get("data_type") or "").strip().lower()}
        return catalog

    @staticmethod
    def _workspace_table_ids_with_column(
        plan: DomainPlan,
        *,
        column_name: str,
        column_catalog: Optional[Dict[tuple[int, str], Dict[str, Any]]] = None,
    ) -> set[int]:
        wanted = str(column_name or "").strip().lower()
        if not wanted:
            return set()
        catalog = column_catalog or {}
        out: set[int] = set()
        for t in (plan.tables or []):
            wt_id = int(t.workspace_table_id)
            if (wt_id, wanted) in catalog:
                out.add(wt_id)
        return out

    @staticmethod
    def _optional_bool(value: Any) -> Optional[bool]:
        if value is None:
            return None
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str):
            v = value.strip().lower()
            if v in {"1", "true", "t", "yes", "y", "on"}:
                return True
            if v in {"0", "false", "f", "no", "n", "off"}:
                return False
        return None

    @classmethod
    def _is_tdoe_severity_filter_enabled(cls, q: Dict[str, Any]) -> bool:
        meta = q.get("meta")
        meta_obj = meta if isinstance(meta, dict) else {}

        direct_flag = cls._optional_bool(meta_obj.get("apply_tdoe_severity_filter"))
        if direct_flag is None:
            direct_flag = cls._optional_bool(q.get("apply_tdoe_severity_filter"))
        if direct_flag is not None:
            return direct_flag

        include_error_rows = cls._optional_bool(meta_obj.get("include_error_rows"))
        if include_error_rows is None:
            include_error_rows = cls._optional_bool(q.get("include_error_rows"))
        if include_error_rows is not None:
            return not include_error_rows

        return True

    @staticmethod
    def _severity_predicate_for_alias(
        *,
        alias: str,
        workspace_table_id: int,
        severity_table_ids: set[int],
    ) -> str:
        if int(workspace_table_id) not in severity_table_ids:
            return ""
        return f"{alias}.{GLOBAL_ROW_QUALITY_COLUMN} < {GLOBAL_ROW_QUALITY_MAX_EXCLUSIVE}"

    def _validate_and_normalize_derived_for_plan(
        self,
        q: Dict[str, Any],
        plan: DomainPlan,
        *,
        column_catalog: Optional[Dict[tuple[int, str], Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        catalog = column_catalog if column_catalog is not None else self._load_domain_column_catalog(plan)
        normalized, issues, _ = validate_and_normalize_derived_sqljson(
            q,
            plan=plan,
            column_catalog=catalog,
            strict=False,
        )
        if issues:
            first = issues[0]
            raise ForgeError(
                f"derived_validation_failed: {first.get('code')} at {first.get('path')}",
                status_code=400,
                details={"issues": issues},
            )
        return normalized

    @staticmethod
    def _is_and_only_filter_tree(node: Any) -> bool:
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
        return all(QueryForgeService._is_and_only_filter_tree(child) for child in children)

    @staticmethod
    def _flatten_and_conditions(node: Any) -> List[Dict[str, Any]]:
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
            out.extend(QueryForgeService._flatten_and_conditions(child))
        return out

    @staticmethod
    def _build_and_filter_tree(conditions: Sequence[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        clean = [c for c in conditions if isinstance(c, dict)]
        if not clean:
            return None
        if len(clean) == 1:
            return clean[0]
        return {"type": "group", "match": "and", "children": clean}

    def compile(self, q: Dict[str, Any], mode: str = "preview", limit: int = 200, offset: int = 0) -> ForgeCompiledQuery:
        if mode not in ("preview", "export"):
            raise ForgeError("Invalid mode", status_code=400)

        filters = self._qf_norm_filters(q.get("filters"))
        q = dict(q)
        q["filters"] = filters

        domain_id = q["domainId"]
        plan = self._domains.resolve_plan(domain_id=domain_id)
        column_catalog = self._load_domain_column_catalog(plan)
        q = self._validate_and_normalize_derived_for_plan(q, plan, column_catalog=column_catalog)

        severity_filter_enabled = self._is_tdoe_severity_filter_enabled(q)
        severity_table_ids = (
            self._workspace_table_ids_with_column(
                plan,
                column_name=GLOBAL_ROW_QUALITY_COLUMN,
                column_catalog=column_catalog,
            )
            if severity_filter_enabled
            else set()
        )

        split_metric = self._detect_split_ratio_metric(q, plan)
        if split_metric is not None:
            return self._compile_split_ratio_query(
                q=q,
                plan=plan,
                split_metric=split_metric,
                mode=mode,
                limit=limit,
                offset=offset,
                severity_table_ids=severity_table_ids,
            )

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
        attachment_required_table_ids = self._qf_attach_table_ids(
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
        base_selects: List[str] = []
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

            for k, v in base_by_modelid.items():
                rewrite_by_modelid.setdefault(k, v)
            for k, v in base_by_wt_col.items():
                rewrite_by_wt_col.setdefault(k, v)
            for k, v in base_by_colname.items():
                rewrite_by_colname.setdefault(k, v)

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
        def _qf_dedupe_projection(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
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

        def _qf_alias_hint_from_expr(qf_expr_sql: str) -> Optional[str]:
            if not isinstance(qf_expr_sql, str):
                return None
            m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\\.([A-Za-z_][A-Za-z0-9_]*)$", qf_expr_sql)
            return m.group(1) if m else None

        def _col_key_for_map(v: Any) -> Optional[tuple]:
            if isinstance(v, dict):
                expr_id = v.get("exprId")
                if expr_id:
                    return ("expr", str(expr_id))
                return ("col", v.get("workspaceTableId"), v.get("modelColumnId"), v.get("columnName"))
            if isinstance(v, str):
                return ("col", None, None, v.strip())
            return None

        filter_table_ids = self._qf_filter_table_ids(filters, plan)
        sorting_table_ids = self._qf_sorting_table_ids(q.get("sorting") or [], plan)

        raw_cols = q.get("columns") or []
        cols = _qf_dedupe_projection(raw_cols)

        alias_by_col: Dict[str, str] = {}
        for c in cols:
            cn = c.get("columnName")
            al = c.get("alias")
            wt_id = c.get("workspaceTableId")
            if cn and al:
                key = f"{wt_id}:{cn}" if wt_id is not None else str(cn)
                alias_by_col[str(key)] = str(al)

        aggs = q.get("aggs") or {"enabled": False}
        distinct = bool(q.get("distinct", False))

        select_exprs: List[str] = []
        group_by_exprs: List[str] = []
        output_names: Dict[str, bool] = {}
        qf_output_cols: List[Dict[str, Any]] = []
        order_alias_by_key: Dict[tuple, str] = {}
        metric_alias_by_ref: Dict[str, str] = {}

        def _qf_reserve_output_name(base_name: str | None, qf_alias_hint: Optional[str]) -> str:
            base = (base_name or "").strip() or "col"
            key = base.lower()
            if not output_names.get(key):
                output_names[key] = True
                return base
            if qf_alias_hint:
                candidate = f"{qf_alias_hint}_{base}"
                key = candidate.lower()
                if not output_names.get(key):
                    output_names[key] = True
                    return candidate
                prefix = candidate
            else:
                prefix = base
            i = 2
            while True:
                candidate = f"{prefix}_{i}"
                key = candidate.lower()
                if not output_names.get(key):
                    output_names[key] = True
                    return candidate
                i += 1

        if aggs and bool(aggs.get("enabled")):
            if distinct:
                raise ForgeError("distinct is not supported with aggregations", status_code=400)
            gb = aggs.get("groupBy") or []
            group_by_exprs = [
                self._col_expr(
                    g,
                    derived_by_exprid,
                    derived_by_name,
                    rewrite_by_colname,
                    rewrite_by_modelid,
                    qf_using_prep,
                    qf_base_alias,
                    alias_by_wt,
                    rewrite_by_wt_col=rewrite_by_wt_col,
                )
                for g in gb
            ]

            for raw_gb, gb_expr in zip(gb, group_by_exprs):
                raw_name = self._col_label_key(raw_gb)
                raw_key = f"{raw_gb.get('workspaceTableId')}:{raw_name}" if isinstance(raw_gb, dict) else raw_name
                user_alias = alias_by_col.get(raw_key)
                qf_alias_hint = None
                if isinstance(raw_gb, dict):
                    wt_id = raw_gb.get("workspaceTableId")
                    if wt_id is not None:
                        try:
                            qf_alias_hint = alias_by_wt.get(int(wt_id))
                        except Exception:
                            qf_alias_hint = None
                qf_alias_hint = qf_alias_hint or _qf_alias_hint_from_expr(gb_expr)
                output_name = _qf_reserve_output_name(user_alias or raw_name, qf_alias_hint)
                select_exprs.append(f"{gb_expr} AS {self._safe_alias(output_name)}")
                qf_output_cols.append({"key": output_name, "label": output_name})
                key = _col_key_for_map(raw_gb)
                if key and key not in order_alias_by_key:
                    order_alias_by_key[key] = output_name

            metric_exprs: List[str] = []
            for m in (aggs.get("metrics") or []):
                fn = (m.get("fn") or "").lower().strip()
                field = m.get("field")
                expr = m.get("expr")
                label = m.get("label")
                metric_ref = str(m.get("metric_ref") or m.get("metricRef") or m.get("id") or "").strip().lower()

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
                output_name = _qf_reserve_output_name(label or fn or "metric", None)
                metric_sql += f" AS {self._safe_alias(output_name)}"
                metric_exprs.append(metric_sql)
                qf_output_cols.append({"key": output_name, "label": output_name})
                if metric_ref:
                    metric_alias_by_ref[metric_ref] = output_name

            select_exprs.extend(metric_exprs)

        else:
            name_counts: Dict[str, int] = {}
            for c in cols:
                cn = c.get("columnName")
                if cn:
                    name_counts[cn] = name_counts.get(cn, 0) + 1

            alias_by_wt_table: Dict[int, str] = {t.workspace_table_id: t.table_alias or t.alias for t in plan.tables}
            for c in cols:
                desired_name = c.get("columnName")
                user_alias = c.get("alias")
                wt_id = c.get("workspaceTableId")
                expr_id = c.get("exprId")

                qf_expr_sql = self._col_expr(
                    c,
                    derived_by_exprid,
                    derived_by_name,
                    rewrite_by_colname,
                    rewrite_by_modelid,
                    qf_using_prep,
                    qf_base_alias,
                    alias_by_wt,
                    rewrite_by_wt_col=rewrite_by_wt_col,
                )

                qf_alias_hint = None
                if wt_id is not None:
                    try:
                        qf_alias_hint = alias_by_wt_table.get(int(wt_id)) if wt_id is not None else qf_base_alias
                    except Exception:
                        qf_alias_hint = None
                if expr_id and not qf_alias_hint:
                    qf_alias_hint = _qf_alias_hint_from_expr(qf_expr_sql)
                base_output_name = user_alias or desired_name
                if not user_alias and desired_name and name_counts.get(desired_name, 0) > 1:
                    alias_base = qf_alias_hint or qf_base_alias
                    base_output_name = f"{alias_base}_{desired_name}"

                output_name = _qf_reserve_output_name(base_output_name, qf_alias_hint)
                col_expr = f"{qf_expr_sql} AS {self._safe_alias(output_name)}"
                select_exprs.append(col_expr)
                key = _col_key_for_map(c)
                if key and key not in order_alias_by_key:
                    order_alias_by_key[key] = output_name
                qf_output_cols.append({"key": output_name, "label": output_name})

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
        if qf_attach_ctx["selects"]:
            if aggs and bool(aggs.get("enabled")):
                raise ForgeError("Attachments with projectFields require non-aggregated queries", status_code=400)
            for expr, qf_out_name in qf_attach_ctx["selects"]:
                # Attachment selects are convenience outputs; skip duplicates already selected by the user.
                if qf_out_name:
                    key = qf_out_name.lower()
                    if output_names.get(key):
                        continue
                    output_names[key] = True
                select_exprs.append(expr)
                if qf_out_name:
                    qf_output_cols.append({"key": qf_out_name, "label": qf_out_name})

        if qf_using_prep and qf_attach_ctx["needs_base_alias"] and from_clause_sql.strip() == "prep":
            from_clause_sql = f"{from_clause_sql} {self._qf_safe_ident(qf_base_alias)}"

        if qf_attach_ctx["joins"]:
            from_clause_sql = f"{from_clause_sql}\n" + "\n".join(qf_attach_ctx["joins"])
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

        select_prefix = "SELECT DISTINCT" if distinct else "SELECT"
        base_where_parts = [
            p
            for p in ([where_sql] if where_sql else []) + (exists_parts or []) + qf_attach_ctx["where"]
            if p
        ]
        if (not qf_using_prep) and primary_severity_pred:
            base_where_parts.insert(0, primary_severity_pred)

        base_patients_cte = ""
        base_patients_cte_count = ""
        if use_two_phase:
            two_phase_key_col_sql = self._qf_safe_ident(str(two_phase_key_col or "patient_id"))
            base_patients_cte = (
                "base_patients AS (\n"
                f"  SELECT DISTINCT {self._qf_safe_ident(qf_base_alias)}.{two_phase_key_col_sql}\n"
                f"  FROM {plan.primary.full_name} {self._qf_safe_ident(qf_base_alias)}\n"
                + (f"  WHERE {' AND '.join(base_where_parts)}\n" if base_where_parts else "")
                + ")"
            )
            base_patients_cte_count = (
                "base_patients AS (\n"
                f"  SELECT DISTINCT {self._qf_safe_ident(qf_base_alias)}.{two_phase_key_col_sql}\n"
                f"  FROM {plan.primary.full_name} {self._qf_safe_ident(qf_base_alias)}\n"
                + (f"  WHERE {' AND '.join(base_where_parts)}\n" if base_where_parts else "")
                + ")"
            )

            projection_table_ids = (projected_table_ids | attachment_required_table_ids | {primary_id}) - {0}
            projection_from_sql = self._from_clause_from_plan(
                plan,
                projection_table_ids,
                severity_table_ids=severity_table_ids,
            )
            projection_lines = projection_from_sql.split("\n")
            join_lines = projection_lines[1:] if len(projection_lines) > 1 else []
            primary_join_parts = [f"{self._qf_safe_ident(qf_base_alias)}.{two_phase_key_col_sql} = bp.{two_phase_key_col_sql}"]
            if primary_severity_pred:
                primary_join_parts.append(primary_severity_pred)
            from_clause_sql = (
                f"base_patients bp\n"
                f"JOIN {plan.primary.full_name} {self._qf_safe_ident(qf_base_alias)} "
                f"ON {' AND '.join(primary_join_parts)}"
            )
            if join_lines:
                from_clause_sql += "\n" + "\n".join(join_lines)

            if qf_attach_ctx["joins"]:
                from_clause_sql = f"{from_clause_sql}\n" + "\n".join(qf_attach_ctx["joins"])

        base_sql = f"{select_prefix} {', '.join(select_exprs)}\nFROM {from_clause_sql}"
        if not use_two_phase:
            if base_where_parts:
                base_sql += f"\nWHERE {' AND '.join(base_where_parts)}"
        if group_by_exprs:
            base_sql += f"\nGROUP BY {', '.join(group_by_exprs)}"

        base_cte_sql = qf_cte_sql

        if base_patients_cte:
            if qf_cte_sql:
                qf_cte_sql = f"{qf_cte_sql},\n{base_patients_cte}"  # pragma: no cover
            else:
                qf_cte_sql = "WITH " + base_patients_cte
        if qf_attach_ctx["ctes"]:
            if qf_cte_sql:
                qf_cte_sql = f"{qf_cte_sql},\n" + ",\n".join(qf_attach_ctx["ctes"])
            else:
                qf_cte_sql = "WITH " + ",\n".join(qf_attach_ctx["ctes"])

        if qf_cte_sql:
            base_sql = f"{qf_cte_sql}\n{base_sql}"

        if use_two_phase:
            cte_sql_count = base_cte_sql
            if base_patients_cte_count:
                if cte_sql_count:
                    cte_sql_count = f"{cte_sql_count},\n{base_patients_cte_count}"  # pragma: no cover
                else:
                    cte_sql_count = "WITH " + base_patients_cte_count
            if qf_attach_ctx["ctes"]:
                if cte_sql_count:
                    cte_sql_count = f"{cte_sql_count},\n" + ",\n".join(qf_attach_ctx["ctes"])
                else:
                    cte_sql_count = "WITH " + ",\n".join(qf_attach_ctx["ctes"])  # pragma: no cover
            base_sql_count = f"{select_prefix} {', '.join(select_exprs)}\nFROM {from_clause_sql}"
            if group_by_exprs:
                base_sql_count += f"\nGROUP BY {', '.join(group_by_exprs)}"  # pragma: no cover
            if cte_sql_count:
                base_sql_count = f"{cte_sql_count}\n{base_sql_count}"
            qf_count_sql = f"SELECT COUNT(*) AS total FROM (\n{base_sql_count}\n) q"
        else:
            qf_count_sql = f"SELECT COUNT(*) AS total FROM (\n{base_sql}\n) q"

        sql = base_sql
        if order_sql:
            sql += f"\nORDER BY {order_sql}"

        if mode == "preview":
            sql += f"\nLIMIT {int(limit)}\nOFFSET {int(offset)}"

        return ForgeCompiledQuery(sql=sql, qf_count_sql=qf_count_sql, params=params, qf_output_cols=qf_output_cols)

    def _detect_split_ratio_metric(self, q: Dict[str, Any], plan: DomainPlan) -> Optional[Dict[str, Any]]:
        aggs = q.get("aggs") or {}
        if not bool(aggs.get("enabled")):
            return None
        metrics = aggs.get("metrics") or []
        ratio_metrics: List[Dict[str, Any]] = []
        primary_id = int(plan.primary.workspace_table_id)
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
            except Exception:
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

    def _compile_split_ratio_query(
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
        if bool(q.get("distinct", False)):
            raise ForgeError("distinct is not supported with aggregations", status_code=400)
        if q.get("dataPrep"):
            raise ForgeError("Split ratio compilation does not support dataPrep", status_code=400)
        if q.get("value_overrideAttachments") or q.get("cohortAttachment"):
            raise ForgeError("Split ratio compilation does not support attachments", status_code=400)
        aggs = q.get("aggs") or {}
        group_by = aggs.get("groupBy") or []
        if not self._is_and_only_filter_tree(q.get("filters")):
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
        except Exception:
            raise ForgeError("Invalid ratio metric table bindings", status_code=400)

        all_conditions = self._flatten_and_conditions(q.get("filters"))
        num_conditions: List[Dict[str, Any]] = []
        den_conditions: List[Dict[str, Any]] = []
        for cond in all_conditions:
            field = cond.get("field")
            if isinstance(field, dict):
                wt_id = field.get("workspaceTableId")
            else:
                wt_id = None
            if wt_id is None:
                wt_id = primary_id
            try:
                wt_id_int = int(wt_id)
            except Exception:
                wt_id_int = primary_id

            if wt_id_int == num_table_id:
                num_conditions.append(cond)
            elif wt_id_int == den_table_id:
                den_conditions.append(cond)
            else:
                num_conditions.append(cond)
                den_conditions.append(cond)

        if self._is_and_only_filter_tree(numerator.get("filters")):
            num_conditions.extend(self._flatten_and_conditions(numerator.get("filters")))
        elif numerator.get("filters") is not None:
            raise ForgeError(
                "derived_validation_failed: unsupported_filter_tree_for_split_ratio at aggs.metrics[0].expr.numerator.filters",
                status_code=400,
                details={
                    "issues": [
                        {
                            "code": "unsupported_filter_tree_for_split_ratio",
                            "path": "aggs.metrics[0].expr.numerator.filters",
                            "message": "Numerator filters must be deterministic AND-only trees",
                        }
                    ]
                },
            )

        if self._is_and_only_filter_tree(denominator.get("filters")):
            den_conditions.extend(self._flatten_and_conditions(denominator.get("filters")))
        elif denominator.get("filters") is not None:
            raise ForgeError(
                "derived_validation_failed: unsupported_filter_tree_for_split_ratio at aggs.metrics[0].expr.denominator.filters",
                status_code=400,
                details={
                    "issues": [
                        {
                            "code": "unsupported_filter_tree_for_split_ratio",
                            "path": "aggs.metrics[0].expr.denominator.filters",
                            "message": "Denominator filters must be deterministic AND-only trees",
                        }
                    ]
                },
            )

        num_filter_tree = self._build_and_filter_tree(num_conditions)
        den_filter_tree = self._build_and_filter_tree(den_conditions)

        params: Dict[str, Any] = {}
        param_counter = 0

        def new_param(val: Any) -> str:
            nonlocal param_counter
            param_counter += 1
            key = f"p{param_counter}"
            params[key] = val
            return f":{key}"

        grain_aliases: List[str] = []
        grain_exprs: List[str] = []
        used_aliases: set[str] = set()
        for idx, gb in enumerate(group_by):
            qf_expr_sql = self._col_expr(
                gb,
                {},
                {},
                {},
                {},
                False,
                qf_base_alias,
                alias_by_wt,
            )
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

            side_query = {
                "columns": [],
                "aggs": {"enabled": True, "groupBy": group_by, "metrics": [{"fn": metric_fn, "field": metric_field}]},
                "sorting": [],
                "filters": filters_node,
                "dataPrep": None,
                "value_overrideAttachments": [],
                "cohortAttachment": None,
            }
            required_table_ids = self._required_table_ids_from_query(side_query, plan)
            required_table_ids.add(int(metric_table_id))
            from_sql = self._from_clause_from_plan(
                plan,
                required_table_ids,
                severity_table_ids=severity_table_ids,
            )

            where_sql, exists_parts = self._compile_where(
                filters_node,
                {},
                {},
                {},
                {},
                False,
                qf_base_alias,
                alias_by_wt,
                plan,
                new_param,
                severity_table_ids=severity_table_ids,
            )
            where_parts = [p for p in ([where_sql] if where_sql else []) + exists_parts if p]
            if primary_severity_pred:
                where_parts.insert(0, primary_severity_pred)

            metric_sql = self._compile_metric(
                metric_fn,
                metric_field,
                {},
                {},
                {},
                {},
                False,
                qf_base_alias,
                alias_by_wt,
                expr=None,
            )
            selects = [f"{qf_expr_sql} AS {self._safe_alias(alias)}" for qf_expr_sql, alias in zip(grain_exprs, grain_aliases)]
            selects.append(f"{metric_sql} AS {self._safe_alias(value_alias)}")
            side_sql = f"{self._qf_safe_ident(cte_name)} AS (\n  SELECT {', '.join(selects)}\n  FROM {from_sql}"
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
        ratio_expr = "num.num_val / NULLIF(den.den_val, 0)" if bool(expr.get("safe_divide", True)) else "num.num_val / den.den_val"
        multiply_by = expr.get("multiply_by")
        if isinstance(multiply_by, (int, float)):
            ratio_expr = f"({ratio_expr}) * {float(multiply_by)}"

        select_list = [f"num.{self._qf_safe_ident(alias)} AS {self._safe_alias(alias)}" for alias in grain_aliases]
        select_list.append(f"{ratio_expr} AS {self._safe_alias(metric_label)}")

        debug_enabled = bool(((q.get("meta") or {}).get("debug")))
        if debug_enabled:
            select_list.append("num.num_val AS numerator_value")
            select_list.append("den.den_val AS denominator_value")

        if grain_aliases:
            join_on = " AND ".join(f"num.{self._qf_safe_ident(alias)} = den.{self._qf_safe_ident(alias)}" for alias in grain_aliases)
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
        for entry in (q.get("sorting") or []):
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
                order_sql = f"{self._safe_alias(alias)} {direction.upper()}"
                break
        if not order_sql and grain_aliases:
            order_sql = ", ".join(f"{self._safe_alias(alias)} ASC" for alias in grain_aliases)

        sql = base_sql
        if order_sql:
            sql += f"\nORDER BY {order_sql}"
        if mode == "preview":
            sql += f"\nLIMIT {int(limit)}\nOFFSET {int(offset)}"

        qf_output_cols = [{"key": alias, "label": alias} for alias in grain_aliases]
        qf_output_cols.append({"key": metric_label, "label": metric_label})
        if debug_enabled:
            qf_output_cols.append({"key": "numerator_value", "label": "numerator_value"})
            qf_output_cols.append({"key": "denominator_value", "label": "denominator_value"})
        return ForgeCompiledQuery(sql=sql, qf_count_sql=qf_count_sql, params=params, qf_output_cols=qf_output_cols)

    # -----------------------------
    # Data Prep compilation (CTE)
    # -----------------------------
    def _qf_compile_dp_cte(
        self,
        data_prep: Any,
        *,
        base_from_sql: str,
        qf_base_alias: str,
        alias_by_wt: Dict[int, str],
    ) -> Dict[str, Any]:
        dp_meta = self._compile_data_prep_meta(
            data_prep,
            qf_base_alias=qf_base_alias,
            alias_by_wt=alias_by_wt,
        )

        qf_using_prep = bool(dp_meta.get("exprs"))
        if not qf_using_prep:
            return {
                "qf_cte_sql": "",
                "from_clause_sql": base_from_sql,
                **dp_meta,
            }

        base_selects = [f"{qf_base_alias}.*"] if qf_base_alias else ["*"]

        qf_cte_sql = self._render_data_prep_cte(
            base_from_sql=base_from_sql,
            base_selects=base_selects,
            exprs=dp_meta["exprs"],
        )
        return {
            "qf_cte_sql": qf_cte_sql,
            "from_clause_sql": "prep",
            **dp_meta,
        }

    def _compile_data_prep_meta(
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
        qf_using_prep = False  # compiling inside CTE against src

        def qf_normalize_date_fmt(fmt: Any) -> Optional[str]:
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

            # ✅ Always use an internal identifier to avoid collisions with SELECT *
            qf_out_ident = self._dp_ident(qf_out_name)

            target_expr = None
            if op != "concat":
                target_expr = self._col_expr(
                    target,
                    derived_by_exprid,
                    derived_by_name,
                    rewrite_by_colname,
                    rewrite_by_modelid,
                    qf_using_prep,
                    qf_base_alias,
                    alias_by_wt,
                    rewrite_by_wt_col=rewrite_by_wt_col,
                )

            if op == "fill_empty":
                treat_blank = bool(r.get("treatBlankAsEmpty"))
                val = r.get("value")
                fb = r.get("fallbackCol")

                base = target_expr
                if treat_blank:
                    base = f"NULLIF(TRIM({target_expr}), '')"

                if fb:
                    fb_expr = self._col_expr(
                        fb,
                        derived_by_exprid,
                        derived_by_name,
                        rewrite_by_colname,
                        rewrite_by_modelid,
                        qf_using_prep,
                        qf_base_alias,
                        alias_by_wt,
                        rewrite_by_wt_col=rewrite_by_wt_col,
                    )
                    expr = f"COALESCE({base}, {fb_expr})"
                else:
                    expr = f"COALESCE({base}, {self._literal_sql(val)})"

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
                fmt = qf_normalize_date_fmt(r.get("format", None))
                if fmt:
                    exprs.append(f"TO_DATE({target_expr}, {self._literal_sql(fmt)}) AS {qf_out_ident}")
                else:
                    exprs.append(f"TO_DATE({target_expr}) AS {qf_out_ident}")

            elif op == "date_part":
                part = (r.get("part") or "").strip().lower()
                if part not in ("year", "month", "day"):
                    raise ForgeError("date_part.part must be year|month|day", status_code=400)
                fn = part.upper()
                # Use YEAR/MONTH/DAY to compare numerically instead of DATE = '2024' string comparisons.
                exprs.append(f"{fn}({target_expr}) AS {qf_out_ident}")

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
                sep_sql = self._literal_sql(separator)

                nulls_mode = (r.get("nulls") or "skip").strip().lower()
                if nulls_mode not in ("skip", "propagate", "empty"):
                    raise ForgeError("concat.nulls must be skip|propagate|empty", status_code=400)

                parts: List[str] = []
                for j, ref in enumerate(inputs):
                    if not isinstance(ref, dict):
                        raise ForgeError(f"concat.inputs[{j}] must be an object", status_code=400)
                    ref_type = (ref.get("type") or "").strip().lower()
                    if ref_type == "column":
                        expr = self._col_expr(
                            ref.get("col"),
                            derived_by_exprid,
                            derived_by_name,
                            rewrite_by_colname,
                            rewrite_by_modelid,
                            qf_using_prep,
                            qf_base_alias,
                            alias_by_wt,
                            rewrite_by_wt_col=rewrite_by_wt_col,
                        )
                    elif ref_type == "literal":
                        expr = self._literal_sql(ref.get("value"))
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
                        for idx, part in enumerate(parts):
                            if idx:
                                interleaved.append(sep_sql)
                            interleaved.append(part)
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

            # ✅ query-wide rewrite: target -> internal output identifier
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

    def _render_data_prep_cte(
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
        joined_exprs = ",\n    ".join(select_exprs)
        sql = (
            "WITH prep AS (\n"
            "  SELECT\n"
            f"    {joined_exprs}\n"
            f"  FROM {base_from_sql}\n"
        )
        if base_where_sql:
            sql += f"  WHERE {base_where_sql}\n"
        sql += ")"
        return sql

    def _from_clause_from_plan(
        self,
        plan: DomainPlan,
        required_table_ids: set[int],
        *,
        severity_table_ids: Optional[set[int]] = None,
    ) -> str:
        if severity_table_ids is None:
            severity_table_ids = set()
        tables_by_id = {t.workspace_table_id: t for t in plan.tables}
        needed_edges: Dict[tuple[str, int, int], Any] = {}
        for wt_id in required_table_ids:
            if int(wt_id) == int(plan.primary.workspace_table_id):
                continue
            for edge in self._domains.get_join_path(plan, int(wt_id)):
                needed_edges[(str(edge.join_id), int(edge.from_workspace_table_id), int(edge.to_workspace_table_id))] = edge

        joined = {plan.primary.workspace_table_id}
        clauses = [f"{plan.primary.full_name} {self._qf_safe_ident(plan.primary.alias)}"]
        remaining_edges = sorted(
            needed_edges.values(),
            key=lambda edge: (int(getattr(edge, "sort_order", 0)), str(edge.join_id)),
        )
        while remaining_edges:
            progress = False
            deferred: List[Any] = []
            for edge in remaining_edges:
                if edge.from_workspace_table_id == edge.to_workspace_table_id:
                    raise ForgeError("Join cannot reference the same table", status_code=400)
                if edge.from_workspace_table_id not in tables_by_id or edge.to_workspace_table_id not in tables_by_id:
                    raise ForgeError("Join references table not in domain", status_code=400)
                if edge.from_workspace_table_id not in joined:
                    deferred.append(edge)
                    continue

                join_type = (edge.join_type or "").upper()
                if join_type not in {"INNER", "LEFT", "RIGHT"}:
                    raise ForgeError(f"Invalid join_type: {join_type}", status_code=400)

                to_table = tables_by_id[edge.to_workspace_table_id]
                on_sql = self._qf_compile_join_on(edge, plan.alias_by_workspace_table_id)
                severity_pred = self._severity_predicate_for_alias(
                    alias=self._qf_safe_ident(to_table.alias),
                    workspace_table_id=int(to_table.workspace_table_id),
                    severity_table_ids=severity_table_ids,
                )
                if severity_pred:
                    on_sql = f"{on_sql} AND {severity_pred}"
                clauses.append(
                    f"{join_type} JOIN {to_table.full_name} {self._qf_safe_ident(to_table.alias)} ON {on_sql}"
                )
                joined.add(edge.to_workspace_table_id)
                progress = True

            if progress:
                remaining_edges = deferred
                continue

            raise ForgeError("Join order invalid: from table not yet joined", status_code=400)

        missing = [t.workspace_table_id for t in plan.tables if t.workspace_table_id in required_table_ids and t.workspace_table_id not in joined]
        if missing:
            raise ForgeError("Domain join plan does not cover all tables", status_code=400)

        return "\n".join(clauses)

    def _qf_compile_join_on(self, edge: Any, alias_by_wt: Dict[int, str]) -> str:
        from_alias = alias_by_wt.get(int(edge.from_workspace_table_id))
        to_alias = alias_by_wt.get(int(edge.to_workspace_table_id))
        if not from_alias or not to_alias:
            raise ForgeError("Join references table not in domain", status_code=400)

        return " AND ".join(self._qf_join_predicates(edge, from_alias, to_alias))

    def _qf_join_predicates(self, edge: Any, from_alias: str, to_alias: str) -> List[str]:
        spec = edge.join_spec or {}
        on_list = spec.get("on") or []
        if not isinstance(on_list, list) or not on_list:
            raise ForgeError("Join spec must include non-empty on[]", status_code=400)

        preds = []
        for item in on_list:
            if not isinstance(item, dict):
                raise ForgeError("Join spec on[] must be objects", status_code=400)

            left = item.get("left") or {}
            right = item.get("right") or {}

            left_wt = left.get("workspaceTableId")
            right_wt = right.get("workspaceTableId")
            if left_wt is not None and int(left_wt) != int(edge.from_workspace_table_id):
                raise ForgeError("Join spec left.workspaceTableId must match from table", status_code=400)
            if right_wt is not None and int(right_wt) != int(edge.to_workspace_table_id):
                raise ForgeError("Join spec right.workspaceTableId must match to table", status_code=400)

            left_expr = self._compile_join_side(left, expected_scope="from", alias=from_alias)
            right_expr = self._compile_join_side(right, expected_scope="to", alias=to_alias)

            preds.append(f"{left_expr} = {right_expr}")

        return preds

    def _compile_join_side(self, side: Dict[str, Any], *, expected_scope: str, alias: str) -> str:
        expr = side.get("expr")
        if expr:
            scope, col, key = self._parse_join_expr(expr)
            if scope != expected_scope:
                raise ForgeError("Join spec expr uses wrong table scope", status_code=400)
            return f"get_json_object({self._qf_safe_ident(alias)}.{self._qf_safe_ident(col)}, '$.{key}')"

        col = side.get("columnName") or side.get("col")
        if not col or not isinstance(col, str) or "." in col:
            raise ForgeError("Join spec column invalid", status_code=400)
        return f"{self._qf_safe_ident(alias)}.{self._qf_safe_ident(col)}"

    def _parse_join_expr(self, expr: str) -> tuple[str, str, str]:
        pattern = r"^get_json_object\(\{(from|to)\}\.([A-Za-z0-9_]+),\s*'\$\.([A-Za-z0-9_]+)'\)$"
        match = re.match(pattern, expr)
        if not match:
            raise ForgeError(
                "Join spec expr must match get_json_object({from|to}.<col>, '$.<key>')",
                status_code=400,
            )
        return match.group(1), match.group(2), match.group(3)

    def _effective_filter_mode(self, plan: DomainPlan, workspace_table_id: int) -> str:
        for t in plan.tables:
            if int(t.workspace_table_id) == int(workspace_table_id):
                if t.is_primary:
                    return "WHERE"
                if t.filter_mode == "AUTO":
                    return "WHERE"
                return t.filter_mode
        raise ForgeError("workspaceTableId is not in domain", status_code=400)

    def _required_table_ids_from_query(self, q: Dict[str, Any], plan: DomainPlan) -> set[int]:
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

    def _collect_required_column_keys(
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
            norm = self._qf_norm_col_key(v, path)
            expr_id = norm.get("exprId")
            mid = norm.get("modelColumnId")
            # Treat exprId-based refs as derived unless they carry a concrete modelColumnId.
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

    def _build_prep_base_selects(
        self,
        required_cols: List[Dict[str, Any]],
        *,
        primary_id: int,
        qf_base_alias: str,
        alias_by_wt: Dict[int, str],
    ) -> Tuple[List[str], Dict[str, str], Dict[int, str], Dict[tuple, str]]:
        if not required_cols:
            return [], {}, {}, {}

        name_counts: Dict[str, int] = {}
        refs_by_name: Dict[str, List[Dict[str, Any]]] = {}
        for c in required_cols:
            cn = c.get("columnName") or ""
            name_counts[cn] = name_counts.get(cn, 0) + 1
            refs_by_name.setdefault(cn, []).append(c)

        used: set[str] = set()

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

        base_selects: List[str] = []
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
            except Exception:
                continue

            alias = alias_by_wt.get(wt_id_int) or (qf_base_alias if wt_id_int == primary_id else None)
            if not alias:
                raise ForgeError("workspaceTableId is not in domain", status_code=400)

            qf_alias_hint = alias_by_wt.get(wt_id_int) or (qf_base_alias if wt_id_int == primary_id else f"t{wt_id_int}")

            qf_out_name = cn
            if name_counts.get(cn, 0) > 1:
                if wt_id_int != primary_id:
                    qf_out_name = f"{qf_alias_hint}_{cn}"
            qf_out_name = unique_name(qf_out_name)

            base_selects.append(
                f"{self._qf_safe_ident(alias)}.{self._qf_safe_ident(cn)} AS {self._qf_safe_ident(qf_out_name)}"
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

        return base_selects, by_colname, by_modelid, by_wt_col

    def _qf_render_sql(self, sql: str, params: Dict[str, Any]) -> str:
        if not sql or not params:
            return sql

        def render_value(v: Any) -> str:
            if isinstance(v, (list, tuple, set)):
                return "(" + ", ".join(self._literal_sql(x) for x in v) + ")"
            return self._literal_sql(v)

        def repl(match: re.Match) -> str:
            key = match.group(0).lstrip(":")
            v = params.get(key, None)
            if v is None and key not in params:
                return match.group(0)
            return render_value(v)

        return re.sub(r":p\d+", repl, sql)

    def _literal_sql(self, v: Any) -> str:
        if v is None:
            return "NULL"
        if isinstance(v, bool):
            return "TRUE" if v else "FALSE"
        if isinstance(v, (int, float)):
            return str(v)
        s = str(v)
        s = s.replace("\\", "\\\\").replace("'", "''")
        return f"'{s}'"

    # -----------------------------
    # Helpers (safe identifiers)
    # -----------------------------
    def _qf_safe_ident(self, s: str) -> str:
        if not s or not isinstance(s, str) or not self._IDENT_RE.match(s):
            raise ForgeError(f"Invalid identifier: {s}", status_code=400)
        return s

    def _safe_table_full_name(self, name: str) -> str:
        if not name or not isinstance(name, str):
            raise ForgeError("Invalid table name", status_code=400)
        parts = [p.strip() for p in name.split(".") if p.strip()]
        if not parts:
            raise ForgeError("Invalid table name", status_code=400)
        return ".".join(f"`{self._qf_safe_ident(p)}`" for p in parts)

    def _safe_alias(self, s: str) -> str:
        if s is None or not isinstance(s, str):
            raise ForgeError("Invalid alias", status_code=400)

        v = s.strip()
        if not v:
            raise ForgeError("Invalid alias", status_code=400)

        if self._IDENT_RE.match(v):
            return v

        if any(ord(ch) < 32 for ch in v):
            raise ForgeError("Invalid alias (control characters)", status_code=400)

        v = v.replace("`", "``")
        return f"`{v}`"

    def _dp_ident(self, qf_out_name: str) -> str:
        """
        Internal DP column identifier, guaranteed safe and collision-resistant.
        Example: qf_out_name="claim type" -> "__dp_claim_type"
        """
        base = re.sub(r"[^A-Za-z0-9_]+", "_", (qf_out_name or "").strip())
        if not base:
            base = "col"
        # ensure doesn't start with a digit
        if base[0].isdigit():
            base = f"c_{base}"
        return self._qf_safe_ident(f"__dp_{base}")

    def _project_expr(self, expr: str, desired_name: str | None, user_alias: str | None) -> str:
        """
        When we rewrite to internal dp columns (e.g. __dp_claim_type), project back to the
        expected user-facing name unless user_alias is provided.
        """
        if user_alias:
            return f"{expr} AS {self._safe_alias(user_alias)}"
        if desired_name and isinstance(desired_name, str) and desired_name.strip():
            if expr != desired_name and expr.startswith("__dp_"):
                return f"{expr} AS {self._qf_safe_ident(desired_name)}"
        return expr

    def _col_label_key(self, k: Any) -> str:
        if isinstance(k, dict):
            return str(k.get("columnName") or "")
        return str(k or "")

    def _col_expr(
        self,
        key_or_ref: Any,
        derived_by_exprid: Dict[str, str],
        derived_by_name: Dict[str, str],
        rewrite_by_colname: Dict[str, str],
        rewrite_by_modelid: Dict[int, str],
        qf_using_prep: bool,
        qf_base_alias: str,
        alias_by_wt: Dict[int, str],
        *,
        rewrite_by_wt_col: Optional[Dict[tuple, str]] = None,
    ) -> str:
        if rewrite_by_wt_col is None:
            rewrite_by_wt_col = {}
        # legacy string
        if isinstance(key_or_ref, str):
            cn = key_or_ref.strip()
            if "." in cn:
                raise ForgeError(f"Qualified column names are not allowed: {cn}", status_code=400)

            if qf_using_prep and cn in rewrite_by_colname:
                return rewrite_by_colname[cn]

            return self._physical_col_expr(cn, qf_using_prep=qf_using_prep, qf_base_alias=qf_base_alias, alias=None)

        if not isinstance(key_or_ref, dict):
            raise ForgeError("Invalid column reference", status_code=400)

        expr_id = key_or_ref.get("exprId")
        cn = key_or_ref.get("columnName")
        mid = key_or_ref.get("modelColumnId")
        wt_id = key_or_ref.get("workspaceTableId")

        if expr_id and expr_id in derived_by_exprid:
            return derived_by_exprid[expr_id]

        if cn and cn in derived_by_name:
            return derived_by_name[cn]

        if not cn or not isinstance(cn, str):
            raise ForgeError("Invalid columnName", status_code=400)
        if "." in cn:
            raise ForgeError(f"Qualified column names are not allowed: {cn}", status_code=400)

        if qf_using_prep:
            if isinstance(mid, int) and mid in rewrite_by_modelid:
                return rewrite_by_modelid[mid]
            if wt_id is not None:
                try:
                    wt_id_int = int(wt_id)
                except Exception:
                    wt_id_int = None
                if wt_id_int is not None:
                    mapped = rewrite_by_wt_col.get((wt_id_int, cn))
                    if mapped:
                        return mapped
            if cn in rewrite_by_colname:
                return rewrite_by_colname[cn]

        alias = None
        if wt_id is not None:
            try:
                wt_id_int = int(wt_id)
            except Exception:
                raise ForgeError("Invalid workspaceTableId", status_code=400)
            alias = alias_by_wt.get(wt_id_int)
            if not alias:
                raise ForgeError("workspaceTableId is not in domain", status_code=400)

        return self._physical_col_expr(cn, qf_using_prep=qf_using_prep, qf_base_alias=qf_base_alias, alias=alias)

    def _physical_col_expr(self, col_name: str, qf_using_prep: bool, qf_base_alias: str, alias: str | None) -> str:
        if not col_name or not isinstance(col_name, str):
            raise ForgeError("Invalid columnName", status_code=400)
        if "." in col_name:
            raise ForgeError(f"Qualified column names are not allowed: {col_name}", status_code=400)

        if qf_using_prep:
            return self._qf_safe_ident(col_name)

        base = alias or qf_base_alias
        return f"{self._qf_safe_ident(base)}.{self._qf_safe_ident(col_name)}"

    # -----------------------------
    # Metric compilation
    # -----------------------------
    def _compile_metric(
        self,
        fn: str,
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
            return f"{fn.upper()}({self._col_expr(field, derived_by_exprid, derived_by_name, rewrite_by_colname, rewrite_by_modelid, qf_using_prep, qf_base_alias, alias_by_wt, rewrite_by_wt_col=rewrite_by_wt_col)})"

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
            num_sql = self._compile_metric(
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
            den_sql = self._compile_metric(
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
                return "COUNT(*)" if not field else f"COUNT({self._col_expr(field, derived_by_exprid, derived_by_name, rewrite_by_colname, rewrite_by_modelid, qf_using_prep, qf_base_alias, alias_by_wt, rewrite_by_wt_col=rewrite_by_wt_col)})"
            if legacy == "COUNT DISTINCT":
                if not field:
                    raise ForgeError("count_distinct requires a field", status_code=400)
                return f"COUNT(DISTINCT {self._col_expr(field, derived_by_exprid, derived_by_name, rewrite_by_colname, rewrite_by_modelid, qf_using_prep, qf_base_alias, alias_by_wt, rewrite_by_wt_col=rewrite_by_wt_col)})"
            if legacy in ("SUM", "AVG", "MIN", "MAX"):
                if not field:
                    raise ForgeError(f"{legacy} requires a field", status_code=400)
                return f"{legacy}({self._col_expr(field, derived_by_exprid, derived_by_name, rewrite_by_colname, rewrite_by_modelid, qf_using_prep, qf_base_alias, alias_by_wt, rewrite_by_wt_col=rewrite_by_wt_col)})"

        raise ForgeError(f"Unsupported metric fn: {fn}", status_code=400)

    # -----------------------------
    # WHERE compilation (parameterized)
    # -----------------------------
    def _compile_where(
        self,
        node: Any,
        derived_by_exprid: Dict[str, str],
        derived_by_name: Dict[str, str],
        rewrite_by_colname: Dict[str, str],
        rewrite_by_modelid: Dict[int, str],
        qf_using_prep: bool,
        qf_base_alias: str,
        alias_by_wt: Dict[int, str],
        plan: DomainPlan,
        new_param: Callable[[Any], str],
        *,
        rewrite_by_wt_col: Optional[Dict[tuple, str]] = None,
        force_exists_for_tables: Optional[set[int]] = None,
        severity_table_ids: Optional[set[int]] = None,
    ) -> Tuple[str, List[str]]:
        if rewrite_by_wt_col is None:
            rewrite_by_wt_col = {}
        if severity_table_ids is None:
            severity_table_ids = set()
        if not node:
            return "", []
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
                    except Exception:
                        try:
                            parsed = ast.literal_eval(s)
                        except Exception:
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
            if len(values) > QF_MAX_MANUAL_IN:
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
            # Keep geo/institution names as exact semantics unless caller explicitly uses contains.
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
                        col = VALUE_OVERRIDE_IN_COLUMN_BY_TYPE[list_type]
                        table_sql = self._safe_table_full_name(table)
                        in_op = "NOT IN" if negate else "IN"
                        return (
                            f"{field_expr} {in_op} (SELECT {self._qf_safe_ident(col)} "
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

            return f"{self._qf_safe_ident(sub_alias)}.{self._qf_safe_ident(cn)}"

        def render_exists(group_key: str, group_info: Dict[str, Any]) -> str:
            nonlocal exists_counter
            exists_counter += 1
            sub_alias = f"e{exists_counter}"

            target_id = int(group_info["workspace_table_id"])
            path = self._domains.get_join_path(plan, target_id)

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

            join_clauses = [f"{first_table.full_name} {self._qf_safe_ident(to_alias)}"]

            where_preds: List[str] = []
            where_preds.extend(self._qf_join_predicates(first_edge, from_alias, to_alias))
            first_severity_pred = self._severity_predicate_for_alias(
                alias=self._qf_safe_ident(to_alias),
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
                join_preds = self._qf_join_predicates(edge, current_alias, next_alias)
                next_severity_pred = self._severity_predicate_for_alias(
                    alias=self._qf_safe_ident(next_alias),
                    workspace_table_id=next_id,
                    severity_table_ids=severity_table_ids,
                )
                if next_severity_pred:
                    join_preds.append(next_severity_pred)
                join_clauses.append(
                    f"JOIN {next_table.full_name} {self._qf_safe_ident(next_alias)} "
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
                        exists_parts = [render_exists(k, v) for k, v in ex.items()]
                        expr_parts = [p for p in ([w_sql] if w_sql else []) + exists_parts if p]
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
                    wt_id = plan.primary.workspace_table_id

                mode = "WHERE" if is_virtual_expr else self._effective_filter_mode(plan, int(wt_id))
                if (
                    not is_virtual_expr
                    and force_exists_for_tables
                    and wt_id is not None
                    and int(wt_id) in force_exists_for_tables
                ):
                    mode = "EXISTS"
                if is_virtual_expr and mode == "EXISTS":
                    raise ForgeError("Virtual expr fields cannot be EXISTS filters", status_code=500)  # pragma: no cover

                op = n.get("op")
                value = n.get("value")

                if mode == "WHERE":
                    if isinstance(field, str):
                        if "." in field:
                            raise ForgeError(f"Qualified column names are not allowed in filters: {field}", status_code=400)
                        if qf_using_prep and field in rewrite_by_colname:
                            field_expr = rewrite_by_colname[field]
                        else:
                            field_expr = self._physical_col_expr(field, qf_using_prep=qf_using_prep, qf_base_alias=qf_base_alias, alias=None)
                    else:
                        field_expr = self._col_expr(
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

                if mode == "EXISTS":
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
        exists_parts = [render_exists(k, v) for k, v in exists_groups.items()]
        return where_sql, exists_parts

    def _compile_attachments(
        self,
        *,
        value_override_attachments: List[Any],
        cohort_attachment: Optional[Dict[str, Any]],
        derived_by_exprid: Dict[str, str],
        derived_by_name: Dict[str, str],
        rewrite_by_colname: Dict[str, str],
        rewrite_by_modelid: Dict[int, str],
        rewrite_by_wt_col: Optional[Dict[tuple, str]] = None,
        qf_using_prep: bool,
        qf_base_alias: str,
        alias_by_wt: Dict[int, str],
        plan: DomainPlan,
        new_param: Callable[[Any], str],
    ) -> Dict[str, Any]:
        if rewrite_by_wt_col is None:
            rewrite_by_wt_col = {}
        ctes: List[str] = []
        joins: List[str] = []
        where: List[str] = []
        selects: List[Tuple[str, str]] = []
        needs_base_alias = False
        exprid_sql: Dict[str, str] = {}

        workspace_id = getattr(self._domains, "_workspace_id", None)

        used_ctes: set[str] = set()

        def unique_cte_name(base: str) -> str:
            name = base
            i = 1
            while name in used_ctes:
                i += 1
                name = f"{base}_{i}"
            used_ctes.add(name)
            return name

        def domain_col_expr(col_key: Any, path: str) -> str:
            nonlocal needs_base_alias
            norm = self._qf_norm_col_key(col_key, path)
            expr = self._col_expr(
                norm,
                derived_by_exprid,
                derived_by_name,
                rewrite_by_colname,
                rewrite_by_modelid,
                qf_using_prep,
                qf_base_alias,
                alias_by_wt,
                rewrite_by_wt_col=rewrite_by_wt_col,
            )
            if qf_using_prep and isinstance(expr, str) and self._IDENT_RE.match(expr):
                needs_base_alias = True
                expr = f"{self._qf_safe_ident(qf_base_alias)}.{expr}"
            return expr

        def join_alias_suffix(col_key: Any, idx: int) -> str:
            suffix = ""
            if isinstance(col_key, dict):
                suffix = str(col_key.get("alias") or col_key.get("joinAlias") or col_key.get("columnName") or "")
            elif isinstance(col_key, str):
                suffix = col_key
            suffix = re.sub(r"[^A-Za-z0-9_]+", "_", suffix.strip().lower())
            if not suffix:
                suffix = f"{idx}"
            if suffix[0].isdigit():
                suffix = f"c_{suffix}"
            return suffix

        for i, cw in enumerate(value_override_attachments or []):
            if not isinstance(cw, dict):
                raise ForgeError("value_overrides entries must be objects", status_code=400)
            mode = (cw.get("mode") or "").strip().lower()
            if mode not in ("filter", "join"):
                raise ForgeError("value_override mode must be filter or join", status_code=400)

            list_type = cw.get("listType")
            list_id = cw.get("listId")
            if list_type not in VALUE_OVERRIDE_KEY_BY_TYPE:
                raise ForgeError("Invalid value_override listType", status_code=400)
            if not list_id:
                raise ForgeError("value_override listId is required", status_code=400)
            if not workspace_id:
                raise ForgeError("workspace_id is required for value_overrides", status_code=400)

            cols = cw.get("domainJoinColumns") or []
            if not isinstance(cols, list):
                raise ForgeError(f"value_overrides[{i}].domainJoinColumns must be a list", status_code=400)
            if not cols:
                raise ForgeError("value_overrides requires domainJoinColumns", status_code=400)

            domain_exprs = [domain_col_expr(col, f"value_overrides[{i}].domainJoinColumns[{j}]") for j, col in enumerate(cols)]

            key_col = VALUE_OVERRIDE_KEY_BY_TYPE[list_type]
            table = TABLE_BY_TYPE.get(list_type)
            if not table:
                raise ForgeError("Invalid value_override listType", status_code=400)
            table_sql = self._safe_table_full_name(table)

            ws_param = new_param(workspace_id)
            list_param = new_param(list_id)

            def active_pred(alias: Optional[str]) -> str:
                prefix = f"{self._qf_safe_ident(alias)}." if alias else ""
                return (
                    f"{prefix}workspace_id = {ws_param} "
                    f"AND {prefix}list_id = {list_param} "
                    f"AND ({prefix}expiration_date IS NULL OR {prefix}expiration_date >= current_date())"
                )

            if mode == "filter":
                cw_alias = "cw"
                join_pred = " OR ".join(
                    f"{self._qf_safe_ident(cw_alias)}.{self._qf_safe_ident(key_col)} = {expr}" for expr in domain_exprs
                )
                if len(domain_exprs) > 1:
                    join_pred = f"({join_pred})"
                exists_sql = (
                    "EXISTS (\n"
                    f"SELECT 1 FROM {table_sql} {self._qf_safe_ident(cw_alias)}\n"
                    f"WHERE {active_pred(cw_alias)} AND {join_pred}\n"
                    ")"
                )
                where.append(exists_sql)
                continue

            cte_base = VALUE_OVERRIDE_JOIN_ALIAS_BY_TYPE[list_type]
            cte_name = unique_cte_name(cte_base)

            agg_fields = ", ".join(
                f"MAX({self._qf_safe_ident(f)}) AS {self._qf_safe_ident(f)}" for f in VALUE_OVERRIDE_FIELDS_BY_TYPE[list_type]
            )
            qf_cte_sql = (
                f"{self._qf_safe_ident(cte_name)} AS (\n"
                f"  SELECT workspace_id, list_id, {self._qf_safe_ident(key_col)}, {agg_fields}\n"
                f"  FROM {table_sql}\n"
                f"  WHERE {active_pred(None)}\n"
                f"  GROUP BY workspace_id, list_id, {self._qf_safe_ident(key_col)}\n"
                ")"
            )
            ctes.append(qf_cte_sql)

            project_fields = cw.get("projectFields") or []
            if not isinstance(project_fields, list):
                raise ForgeError("value_override projectFields must be a list", status_code=400)
            allowed = set(VALUE_OVERRIDE_FIELDS_BY_TYPE[list_type])
            for field in project_fields:
                if field not in allowed:
                    raise ForgeError("Invalid value_override project field", status_code=400)

            att_id = (cw.get("id") or f"cw{i+1}")

            separate = bool(cw.get("supportsSeparateAliasJoins") or cw.get("separateAliasJoins"))
            if list_type == "npiCategories" and project_fields and separate and len(domain_exprs) > 1:
                for j, (col_key, expr) in enumerate(zip(cols, domain_exprs)):
                    suffix = join_alias_suffix(col_key, j + 1)
                    join_alias = self._qf_safe_ident(f"{cte_name}_{suffix}")
                    joins.append(
                        f"JOIN {self._qf_safe_ident(cte_name)} {join_alias} "
                        f"ON {join_alias}.{self._qf_safe_ident(key_col)} = {expr}"
                    )
                    for field in project_fields:
                        qf_out_name = f"cw_{suffix}_{field}"
                        qf_expr_sql = f"{join_alias}.{self._qf_safe_ident(field)} AS {self._safe_alias(qf_out_name)}"
                        selects.append((qf_expr_sql, qf_out_name))
                        exprid_sql[f"cw:{att_id}:cw:{suffix}:{field}"] = f"{join_alias}.{self._qf_safe_ident(field)}"
                continue

            join_alias = self._qf_safe_ident(cte_name)
            on_pred = " OR ".join(
                f"{join_alias}.{self._qf_safe_ident(key_col)} = {expr}" for expr in domain_exprs
            )
            if len(domain_exprs) > 1:
                on_pred = f"({on_pred})"
            joins.append(f"JOIN {self._qf_safe_ident(cte_name)} {join_alias} ON {on_pred}")

            for field in project_fields:
                qf_out_name = VALUE_OVERRIDE_PROJECT_ALIASES_BY_TYPE[list_type].get(field) or f"cw_{field}"
                qf_expr_sql = f"{join_alias}.{self._qf_safe_ident(field)} AS {self._safe_alias(qf_out_name)}"
                selects.append((qf_expr_sql, qf_out_name))
                exprid_sql[f"cw:{att_id}:cw:{field}"] = f"{join_alias}.{self._qf_safe_ident(field)}"

        if cohort_attachment:
            raise ForgeError("cohort functionality is no longer supported", status_code=400)

        return {
            "ctes": ctes,
            "joins": joins,
            "where": where,
            "selects": selects,
            "needs_base_alias": needs_base_alias,
            "exprid_sql": exprid_sql,
        }

    # -----------------------------
    # ORDER BY compilation
    # -----------------------------
    def _compile_order_by(
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

    # -----------------------------
    # Column/row inference & shaping
    # -----------------------------
    def _qf_cols_from_json(self, q: dict) -> List[Dict[str, Any]]:
        aggs = (q.get("aggs") or {})
        if aggs.get("enabled"):
            cols: List[Dict[str, Any]] = []

            alias_map = {
                (c.get("columnName")): (c.get("alias") or None)
                for c in (q.get("columns") or [])
                if isinstance(c, dict)
            }

            for gb in (aggs.get("groupBy") or []):
                raw = gb.get("columnName") if isinstance(gb, dict) else str(gb)
                cols.append({"key": raw, "label": (alias_map.get(raw) or raw)})

            for m in (aggs.get("metrics") or []):
                label = (m.get("label") or "").strip() or None
                fn = (m.get("fn") or "").strip() or "metric"
                key = label or fn
                cols.append({"key": key, "label": label or fn})

            return cols

        out: List[Dict[str, Any]] = []
        for c in (q.get("columns") or []):
            if not isinstance(c, dict):
                continue
            k = c.get("alias") or c.get("columnName")
            if not k:
                continue
            out.append({"key": k, "label": k})
        return out

    def _qf_infer_cols(self, rows: List[Any]) -> List[Dict[str, Any]]:
        if not rows:
            return []
        first = rows[0]
        if isinstance(first, dict):
            return [{"key": k, "label": k} for k in first.keys()]
        return []

    def _qf_extract_total(self, count_rows: List[Any]) -> int:
        if not count_rows:
            return 0
        first = count_rows[0]
        if isinstance(first, dict):
            return int(first.get("total") or 0)
        if isinstance(first, (list, tuple)) and len(first) >= 1:
            return int(first[0] or 0)
        return 0

    def _qf_rows_to_dicts(self, qf_result_rows, columns):
        if not qf_result_rows:
            return []

        if isinstance(qf_result_rows, list) and qf_result_rows and isinstance(qf_result_rows[0], dict):
            return qf_result_rows

        if not columns:
            return []

        if isinstance(columns, list) and columns and isinstance(columns[0], dict):
            keys = [c.get("key") for c in columns]
        else:
            keys = list(columns)

        out = []
        for row in qf_result_rows:
            if not isinstance(row, (list, tuple)):
                continue
            out.append({keys[i]: (row[i] if i < len(row) else None) for i in range(len(keys))})
        return out
