from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from app.exceptions.forge_error import ForgeError
from app.services.domain_resolver import DomainPlan
from app.services.query_forge.value_override_constants import VALUE_OVERRIDE_KEY_BY_TYPE
from app.services.sqljson import validate_and_normalize_derived_sqljson

INT_PARSE_ERRORS = (TypeError, ValueError)


class QueryForgeQueryNormalizer:
    def normalize_filters(self, node: Any) -> Any:
        if not isinstance(node, dict):
            return node

        node_type = node.get("type")
        if node_type != "group":
            return node

        match = (node.get("match") or "and").lower()
        children = [self.normalize_filters(c) for c in (node.get("children") or [])]
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

            norm_col = self.normalize_col_key(col_source, path=f"columns[{i}]")
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
            norm_gb.append(self.normalize_col_key(g, path=f"aggs.groupBy[{j}]"))
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

            fn_field = self.extract_metric_field_from_fn_token(fn_input)
            if field is None and fn_field is not None:
                field = fn_field
            if fn_input == "" and field is not None:
                fn_input = "count"
            fn = self.normalize_metric_fn_token(fn_input)
            if fn == "":
                raise ForgeError(f"aggs.metrics[{i}].fn is required", status_code=400)

            expr = None

            norm_field = None
            if fn == "expr":
                expr = self.normalize_metric_expr(m.get("expr"), path=f"aggs.metrics[{i}].expr")
            elif field is not None:
                if fn == "count" and self.is_empty_count_metric_field(field):
                    norm_field = None
                else:
                    norm_field = self.normalize_col_key(field, path=f"aggs.metrics[{i}].field")

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
                col = self.normalize_col_key(s.get("col"), path=f"sorting[{i}].col")
            elif "columnName" in s:
                col = self.normalize_col_key(s.get("columnName"), path=f"sorting[{i}].columnName")
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

        raw_value_override_attachments = q.get("value_overrideAttachments")
        if not raw_value_override_attachments:
            raw_value_override_attachments = q.get("value_overrides")
        q["value_overrideAttachments"] = [
            self._normalize_value_override_attachment(cw, idx)
            for idx, cw in enumerate(self._as_attachment_list(raw_value_override_attachments))
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
    def normalize_metric_fn_token(raw: Any) -> str:
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
    def extract_metric_field_from_fn_token(raw: Any) -> Optional[Dict[str, Any]]:
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
    def is_empty_count_metric_field(field: Any) -> bool:
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

    def normalize_col_key(self, v: Any, path: str) -> Dict[str, Any]:
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

    def normalize_metric_expr(self, expr: Any, path: str) -> Dict[str, Any]:
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

        multiply_by = expr.get("multiply_by", expr.get("multiplyBy"))
        if multiply_by is not None and not isinstance(multiply_by, (int, float)):
            raise ForgeError(f"{path}.multiplyBy must be numeric or null", status_code=400)

        return {
            "kind": "ratio",
            "name": (str(expr.get("name") or "").strip() or None),
            "numerator": self._normalize_metric_expr_part(numerator, f"{path}.numerator"),
            "denominator": self._normalize_metric_expr_part(denominator, f"{path}.denominator"),
            "safe_divide": bool(expr.get("safe_divide", expr.get("safeDivide", True))),
            "multiply_by": float(multiply_by) if isinstance(multiply_by, (int, float)) else None,
        }

    def attachment_table_ids(
        self,
        *,
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
                norm = self.normalize_col_key(col, f"value_overrideAttachments[{i}].domainJoinColumns[{j}]")
                wt_id = norm.get("workspaceTableId") or primary_id
                needed.add(int(wt_id))

        if cohort_attachment:
            if not isinstance(cohort_attachment, dict):
                raise ForgeError("cohortAttachment must be an object", status_code=400)
            col = cohort_attachment.get("domainJoinColumn")
            if col is not None:
                norm = self.normalize_col_key(col, "cohortAttachment.domainJoinColumn")
                wt_id = norm.get("workspaceTableId") or primary_id
                needed.add(int(wt_id))

        return needed

    def filter_table_ids(self, node: Any, plan: DomainPlan) -> set[int]:
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
            except INT_PARSE_ERRORS:
                return
            if wt_id_int != 0:
                ids.add(wt_id_int)

        walk(node)
        return ids

    def sorting_table_ids(self, sorting: List[Dict[str, Any]], plan: DomainPlan) -> set[int]:
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
            except INT_PARSE_ERRORS:
                continue
            if wt_id_int != 0:
                ids.add(wt_id_int)
        return ids

    def _normalize_metric_expr_part(self, part: Dict[str, Any], part_path: str) -> Dict[str, Any]:
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
            norm_field = self.normalize_col_key(field, path=f"{part_path}.field")
        filters = part.get("filters")
        if filters is not None and not isinstance(filters, dict):
            raise ForgeError(f"{part_path}.filters must be an object", status_code=400)
        return {"fn": fn, "field": norm_field, "filters": filters}

    def _normalize_value_override_attachment(self, cw: Any, idx: int) -> Dict[str, Any]:
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
            self.normalize_col_key(col, path=f"value_overrideAttachments[{idx}].domainJoinColumns[{j}]")
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

    @staticmethod
    def _as_attachment_list(raw: Any) -> List[Any]:
        if raw is None:
            return []
        if isinstance(raw, list):
            return raw
        if isinstance(raw, dict):
            return [v for v in raw.values() if v]
        raise ForgeError("value_overrides must be a list or object", status_code=400)
