# app/services/nocode_query_service.py
from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from app.adapters.mysql_sql_executor import MySQLSQLExecutor
from app.exceptions.service_error import ServiceError
from app.ports.sql_executor import SQLExecutor
from app.services.crosswalks.list_schema import TABLE_BY_TYPE
from app.services.domain_resolver import DomainPlan, DomainResolver

MAX_MANUAL_IN = 150

CROSSWALK_IN_COLUMN_BY_TYPE = {
    "regions": "zipcode",
    "npiCategories": "npi",
    "serviceLines": "procedure_code",
}

CROSSWALK_KEY_BY_TYPE = {
    "regions": "zipcode",
    "npiCategories": "npi",
    "serviceLines": "procedure_code",
}

CROSSWALK_JOIN_ALIAS_BY_TYPE = {
    "regions": "cw_regions",
    "npiCategories": "cw_npi",
    "serviceLines": "cw_sl",
}

CROSSWALK_FIELDS_BY_TYPE = {
    "regions": ["region", "subregion"],
    "npiCategories": ["npi_type_code", "customer_npi_category_1", "customer_npi_category_2"],
    "serviceLines": ["customer_service_line", "customer_sub_service_line"],
}

CROSSWALK_PROJECT_ALIASES_BY_TYPE = {
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
class CompiledQuery:
    sql: str
    count_sql: str
    params: Dict[str, Any]
    output_columns: List[Dict[str, Any]]


@dataclass(frozen=True)
class NoCodeRunResult:
    sql: str
    sql_rendered: str
    params: Dict[str, Any]
    rows: List[Any]
    columns: List[Dict[str, Any]]
    total: int
    limit: int
    offset: int


@dataclass(frozen=True)
class NoCodePreparedQuery:
    sql: str
    sql_rendered: str
    params: Dict[str, Any]
    count_sql: str
    columns: List[Dict[str, Any]]
    limit: int
    offset: int


SqlColumnKeyLike = Union[str, Dict[str, Any]]  # legacy strings + new {workspaceTableId?,modelColumnId,columnName,exprId?}


class NoCodeQueryService:
    """
    Notes on safety / correctness:

    - We NEVER trust client-supplied table qualifiers (e.g. "t.col", "schema.t.col").
      The only authoritative FROM is DomainResolver.resolve(domainId).full_name.

    - We alias the base FROM as the primary table alias and compile physical columns as <alias>.<col>.

    - DataPrep compiles into a CTE `prep` which selects from `<domain_fqn> src`.
      Subsequent SELECTs use `FROM prep`.

    - ✅ Important: DataPrep outputs use INTERNAL identifiers (e.g. __dp_claim_type) to avoid
      collisions with `SELECT *` columns inside the CTE. Query-wide references are rewritten
      to these internal identifiers, and projection aliases back to the user-visible name.
    """

    def __init__(self, executor: SQLExecutor, domain_resolver: DomainResolver):
        self._executor = executor
        self._domains = domain_resolver

    def run(
        self,
        raw_query: Dict[str, Any],
        mode: str = "preview",
        limit: int = 200,
        offset: int = 0,
    ) -> NoCodeRunResult:
        normalized = self.normalize(raw_query)
        compiled = self.compile(normalized, mode=mode, limit=limit, offset=offset)

        data = self._executor.submit_statement(compiled.sql, parameters=compiled.params)
        rows_any = (data or {}).get("rows") or []

        count = self._executor.submit_statement(compiled.count_sql, parameters=compiled.params)
        total = self._extract_total((count or {}).get("rows") or [])

        columns = (
            self._infer_columns_from_rows(rows_any)
            or compiled.output_columns
            or self._columns_from_query_json(normalized)
        )
        rows = self._rows_to_dicts(rows_any, columns)

        rendered_sql = self._render_sql_with_params(compiled.sql, compiled.params)

        return NoCodeRunResult(
            sql=compiled.sql,
            sql_rendered=rendered_sql,
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
    ) -> NoCodePreparedQuery:
        normalized = self.normalize(raw_query)
        compiled = self.compile(normalized, mode=mode, limit=limit, offset=offset)
        columns = compiled.output_columns or self._columns_from_query_json(normalized)
        rendered_sql = self._render_sql_with_params(compiled.sql, compiled.params)
        return NoCodePreparedQuery(
            sql=compiled.sql,
            sql_rendered=rendered_sql,
            params=compiled.params,
            count_sql=compiled.count_sql,
            columns=columns,
            limit=limit,
            offset=offset,
        )

    # -----------------------------
    # Normalize / validate
    # -----------------------------
    def _normalize_filters(self, node: Any) -> Any:
        if not isinstance(node, dict):
            return node

        node_type = node.get("type")
        if node_type != "group":
            return node

        match = (node.get("match") or "and").lower()
        children = [self._normalize_filters(c) for c in (node.get("children") or [])]
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
            raise ServiceError("Missing query", status_code=400)

        q = dict(q)

        q.setdefault("version", 1)
        q.setdefault("domainId", None)
        q.setdefault("columns", [])
        q.setdefault("dataPrep", None)
        q.setdefault("filters", None)
        q.setdefault("aggs", {"enabled": False, "metrics": [], "groupBy": []})
        q.setdefault("sorting", [])
        q.setdefault("distinct", False)
        q.setdefault("crosswalkAttachments", [])
        q.setdefault("cohortAttachment", None)
        q.setdefault("crosswalks", [])
        q.setdefault("cohortJoin", None)
        q.setdefault("meta", {})

        if q.get("domainId") is None:
            raise ServiceError("domainId is required", status_code=400)

        distinct = q.get("distinct", False)
        if not isinstance(distinct, bool):
            raise ServiceError("distinct must be a boolean", status_code=400)
        q["distinct"] = distinct

        cols = q.get("columns") or []
        if not isinstance(cols, list):
            raise ServiceError("columns must be a list", status_code=400)

        norm_cols: List[Dict[str, Any]] = []
        for i, c in enumerate(cols):
            if not isinstance(c, dict):
                raise ServiceError(f"columns[{i}] must be an object", status_code=400)

            col_name = c.get("columnName")
            if not col_name or not isinstance(col_name, str):
                raise ServiceError(f"columns[{i}].columnName is required", status_code=400)

            if "." in col_name:
                raise ServiceError(
                    f"columns[{i}].columnName must be an unqualified column name (no dots): {col_name}",
                    status_code=400,
                )

            alias = c.get("alias")
            if alias is not None and not isinstance(alias, str):
                raise ServiceError(f"columns[{i}].alias must be a string or null", status_code=400)
            alias = (alias or "").strip() or None

            expr_id = c.get("exprId", None)
            if expr_id is not None and not isinstance(expr_id, str):
                raise ServiceError(f"columns[{i}].exprId must be a string or null", status_code=400)

            wt_id = c.get("workspaceTableId", None)
            if wt_id is not None and not isinstance(wt_id, int):
                raise ServiceError(f"columns[{i}].workspaceTableId must be number or null", status_code=400)

            norm_cols.append(
                {
                    "workspaceTableId": wt_id,
                    "modelColumnId": c.get("modelColumnId"),
                    "columnName": col_name,
                    "exprId": expr_id,
                    "modelTableId": c.get("modelTableId"),
                    "modelTableName": c.get("modelTableName"),
                    "fullName": c.get("fullName"),
                    "dataType": c.get("dataType"),
                    "nullable": c.get("nullable"),
                    "alias": alias,
                }
            )
        q["columns"] = norm_cols

        aggs = q.get("aggs")
        if aggs is None:
            aggs = {"enabled": False, "metrics": [], "groupBy": []}
        if not isinstance(aggs, dict):
            raise ServiceError("aggs must be an object", status_code=400)

        aggs.setdefault("enabled", False)
        aggs.setdefault("metrics", [])
        aggs.setdefault("groupBy", [])

        gb = aggs.get("groupBy") or []
        if not isinstance(gb, list):
            raise ServiceError("aggs.groupBy must be a list", status_code=400)

        norm_gb: List[Dict[str, Any]] = []
        for j, g in enumerate(gb):
            norm_gb.append(self._normalize_col_key(g, path=f"aggs.groupBy[{j}]"))
        aggs["groupBy"] = norm_gb

        metrics = aggs.get("metrics") or []
        if not isinstance(metrics, list):
            raise ServiceError("aggs.metrics must be a list", status_code=400)

        norm_metrics: List[Dict[str, Any]] = []
        for i, m in enumerate(metrics):
            if not isinstance(m, dict):
                raise ServiceError(f"aggs.metrics[{i}] must be an object", status_code=400)

            fn_raw = (m.get("fn") or "").strip()
            fn = fn_raw.lower().replace(" ", "_")
            if fn in ("countdistinct", "count_distinct", "count-distinct"):
                fn = "count_distinct"
            if fn == "count":
                fn = "count"

            field = m.get("field", None)
            if field is None and "column" in m:
                field = m.get("column")

            norm_field = None
            if field is not None:
                norm_field = self._normalize_col_key(field, path=f"aggs.metrics[{i}].field")

            label = m.get("label")
            if label is not None and not isinstance(label, str):
                raise ServiceError(f"aggs.metrics[{i}].label must be string or null", status_code=400)
            label = (label or "").strip() or None

            mid = m.get("id") or None
            if mid is not None and not isinstance(mid, str):
                raise ServiceError(f"aggs.metrics[{i}].id must be string", status_code=400)

            norm_metrics.append({"id": mid or f"m{i+1}", "fn": fn, "field": norm_field, "label": label})
        aggs["metrics"] = norm_metrics
        q["aggs"] = aggs

        sorting = q.get("sorting") or []
        if not isinstance(sorting, list):
            raise ServiceError("sorting must be a list", status_code=400)

        norm_sort: List[Dict[str, Any]] = []
        for i, s in enumerate(sorting):
            if not isinstance(s, dict):
                raise ServiceError(f"sorting[{i}] must be an object", status_code=400)

            if "col" in s:
                col = self._normalize_col_key(s.get("col"), path=f"sorting[{i}].col")
            else:
                col = self._normalize_col_key(s.get("columnName"), path=f"sorting[{i}].columnName")

            dir_ = (s.get("dir") or "asc").lower()
            if dir_ not in ("asc", "desc"):
                raise ServiceError(f"sorting[{i}].dir must be asc|desc", status_code=400)

            norm_sort.append({"col": col, "dir": dir_})
        q["sorting"] = norm_sort

        if q.get("filters") is None:
            q["filters"] = None

        dp = q.get("dataPrep")
        if dp is not None:
            if not isinstance(dp, dict):
                raise ServiceError("dataPrep must be an object or null", status_code=400)
            dp.setdefault("enabled", bool((dp.get("rules") or [])))
            dp.setdefault("rules", [])
            if not isinstance(dp.get("rules"), list):
                raise ServiceError("dataPrep.rules must be a list", status_code=400)
        q["dataPrep"] = dp

        if (not q.get("columns")) and not bool(q.get("aggs", {}).get("enabled")):
            raise ServiceError("Select at least one column (or enable aggregations).", status_code=400)

        def norm_crosswalk_attachment(cw: Any, idx: int) -> Dict[str, Any]:
            if not isinstance(cw, dict):
                raise ServiceError(f"crosswalkAttachments[{idx}] must be an object", status_code=400)

            list_type = cw.get("listType") or cw.get("type")
            if not list_type or list_type not in CROSSWALK_KEY_BY_TYPE:
                raise ServiceError("Invalid crosswalk listType", status_code=400)

            list_id = cw.get("listId")
            if not list_id or not isinstance(list_id, str):
                raise ServiceError("crosswalk listId is required", status_code=400)

            mode = (cw.get("mode") or "filter").strip().lower()
            if mode not in ("filter", "join"):
                raise ServiceError("crosswalk mode must be filter or join", status_code=400)

            raw_cols = cw.get("domainJoinColumns")
            if raw_cols is None:
                raw_col = cw.get("domainJoinColumn")
                raw_cols = [raw_col] if raw_col is not None else []
            if not isinstance(raw_cols, list):
                raise ServiceError("domainJoinColumns must be a list", status_code=400)

            norm_cols = [
                self._normalize_col_key(col, path=f"crosswalkAttachments[{idx}].domainJoinColumns[{j}]")
                for j, col in enumerate(raw_cols)
            ]

            crosswalk_join_cols = cw.get("crosswalkJoinColumns")
            if crosswalk_join_cols is None:
                crosswalk_join_cols = [CROSSWALK_KEY_BY_TYPE[list_type]]
            if not isinstance(crosswalk_join_cols, list):
                raise ServiceError("crosswalkJoinColumns must be a list", status_code=400)

            project_fields = cw.get("projectFields") or []
            if not isinstance(project_fields, list):
                raise ServiceError("projectFields must be a list", status_code=400)

            return {
                "id": (cw.get("id") if isinstance(cw.get("id"), str) else None),
                "listType": list_type,
                "listId": str(list_id),
                "mode": mode,
                "domainJoinColumns": norm_cols,
                "crosswalkJoinColumns": crosswalk_join_cols,
                "projectFields": project_fields,
                "supportsSeparateAliasJoins": bool(
                    cw.get("supportsSeparateAliasJoins") or cw.get("separateAliasJoins")
                ),
            }

        def norm_cohort_attachment(ch: Any) -> Dict[str, Any]:
            if not isinstance(ch, dict):
                raise ServiceError("cohortAttachment must be an object", status_code=400)

            mode = (ch.get("mode") or "filter").strip().lower()
            if mode not in ("filter", "join"):
                raise ServiceError("cohortAttachment.mode must be filter or join", status_code=400)

            table_name = ch.get("cohortTableFullName")
            if not table_name or not isinstance(table_name, str):
                raise ServiceError("cohortTableFullName is required", status_code=400)

            table_alias = ch.get("cohortTableAlias") or "cohort"
            if not isinstance(table_alias, str) or not table_alias.strip():
                raise ServiceError("cohortTableAlias must be a string", status_code=400)

            join_key = ch.get("cohortJoinKey") or "patient_id"
            if join_key not in ("patient_id", "cohort_key"):
                raise ServiceError("cohortJoinKey must be patient_id or cohort_key", status_code=400)

            domain_col = ch.get("domainJoinColumn")
            if domain_col is None:
                raise ServiceError("cohortAttachment.domainJoinColumn is required", status_code=400)
            norm_domain_col = self._normalize_col_key(domain_col, path="cohortAttachment.domainJoinColumn")

            project_fields = ch.get("projectFields") or []
            if not isinstance(project_fields, list):
                raise ServiceError("projectFields must be a list", status_code=400)

            return {
                "id": (ch.get("id") if isinstance(ch.get("id"), str) else None),
                "mode": mode,
                "cohortTableFullName": table_name,
                "cohortTableAlias": table_alias,
                "cohortJoinKey": join_key,
                "domainJoinColumn": norm_domain_col,
                "cohortKeyFilter": ch.get("cohortKeyFilter"),
                "projectFields": project_fields,
            }

        def as_attachment_list(raw: Any) -> List[Any]:
            if raw is None:
                return []
            if isinstance(raw, list):
                return raw
            if isinstance(raw, dict):
                return [v for v in raw.values() if v]
            raise ServiceError("crosswalks must be a list or object", status_code=400)

        raw_crosswalk_attachments = q.get("crosswalkAttachments")
        if not raw_crosswalk_attachments:
            raw_crosswalk_attachments = q.get("crosswalks")
        q["crosswalkAttachments"] = [
            norm_crosswalk_attachment(cw, idx) for idx, cw in enumerate(as_attachment_list(raw_crosswalk_attachments))
        ]

        raw_cohort_attachment = q.get("cohortAttachment")
        if not raw_cohort_attachment:
            raw_cohort_attachment = q.get("cohortJoin")
        if raw_cohort_attachment is None:
            q["cohortAttachment"] = None
        else:
            q["cohortAttachment"] = norm_cohort_attachment(raw_cohort_attachment)

        return q

    def _normalize_col_key(self, v: Any, path: str) -> Dict[str, Any]:
        if isinstance(v, str):
            s = v.strip()
            if not s:
                raise ServiceError(f"{path} is required", status_code=400)
            if "." in s:
                raise ServiceError(f"{path} must be an unqualified column name (no dots): {s}", status_code=400)
            return {"modelColumnId": None, "columnName": s, "exprId": None}

        if not isinstance(v, dict):
            raise ServiceError(f"{path} must be a column key", status_code=400)

        cn = v.get("columnName")
        if not cn or not isinstance(cn, str):
            raise ServiceError(f"{path}.columnName is required", status_code=400)
        if "." in cn:
            raise ServiceError(f"{path}.columnName must be unqualified (no dots): {cn}", status_code=400)

        mid = v.get("modelColumnId", None)
        if mid is not None and not isinstance(mid, int):
            raise ServiceError(f"{path}.modelColumnId must be number or null", status_code=400)

        expr = v.get("exprId", None)
        if expr is not None and not isinstance(expr, str):
            raise ServiceError(f"{path}.exprId must be string or null", status_code=400)

        wt_id = v.get("workspaceTableId", None)
        if wt_id is not None and not isinstance(wt_id, int):
            raise ServiceError(f"{path}.workspaceTableId must be number or null", status_code=400)

        return {"workspaceTableId": wt_id, "modelColumnId": mid, "columnName": cn, "exprId": expr}

    def _attachment_required_table_ids(
        self,
        crosswalk_attachments: List[Any],
        cohort_attachment: Optional[Dict[str, Any]],
        primary_id: int,
    ) -> set[int]:
        needed: set[int] = set()

        for i, cw in enumerate(crosswalk_attachments or []):
            if not isinstance(cw, dict):
                raise ServiceError("crosswalkAttachments entries must be objects", status_code=400)
            cols = cw.get("domainJoinColumns") or []
            if not isinstance(cols, list):
                raise ServiceError(f"crosswalkAttachments[{i}].domainJoinColumns must be a list", status_code=400)
            for j, col in enumerate(cols):
                norm = self._normalize_col_key(col, f"crosswalkAttachments[{i}].domainJoinColumns[{j}]")
                wt_id = norm.get("workspaceTableId") or primary_id
                needed.add(int(wt_id))

        if cohort_attachment:
            if not isinstance(cohort_attachment, dict):
                raise ServiceError("cohortAttachment must be an object", status_code=400)
            col = cohort_attachment.get("domainJoinColumn")
            if col is not None:
                norm = self._normalize_col_key(col, "cohortAttachment.domainJoinColumn")
                wt_id = norm.get("workspaceTableId") or primary_id
                needed.add(int(wt_id))

        return needed

    # -----------------------------
    # Compile
    # -----------------------------
    _IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

    def _supports_array_params(self) -> bool:
        if hasattr(self._executor, "supports_array_params"):
            return bool(getattr(self._executor, "supports_array_params"))
        return "databricks" in self._executor.__class__.__name__.lower()

    def _filter_table_ids(self, node: Any, plan: DomainPlan) -> set[int]:
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

    def _sorting_table_ids(self, sorting: List[Dict[str, Any]], plan: DomainPlan) -> set[int]:
        ids: set[int] = set()
        for s in sorting:
            if not isinstance(s, dict):
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

    def compile(self, q: Dict[str, Any], mode: str = "preview", limit: int = 200, offset: int = 0) -> CompiledQuery:
        if mode not in ("preview", "export"):
            raise ServiceError("Invalid mode", status_code=400)

        filters = self._normalize_filters(q.get("filters"))
        q = dict(q)
        q["filters"] = filters

        domain_id = q["domainId"]
        plan = self._domains.resolve_plan(domain_id=domain_id)
        primary_id = int(plan.primary.workspace_table_id)
        base_alias = plan.primary.alias
        alias_by_wt = plan.alias_by_workspace_table_id
        crosswalk_attachments = q.get("crosswalkAttachments") or []
        cohort_attachment = q.get("cohortAttachment")
        base_required_table_ids = self._required_table_ids_from_query(q, plan)
        q_no_filters = dict(q)
        q_no_filters["filters"] = None
        projected_table_ids = self._required_table_ids_from_query(q_no_filters, plan)
        filter_only_table_ids = (base_required_table_ids - projected_table_ids) - {primary_id}
        attachment_required_table_ids = self._attachment_required_table_ids(
            crosswalk_attachments,
            cohort_attachment,
            primary_id,
        )
        required_table_ids = base_required_table_ids | attachment_required_table_ids
        required_table_ids.discard(0)
        base_from_sql = self._from_clause_from_plan(plan, required_table_ids)

        dp_ctx = self._compile_data_prep_cte(
            q.get("dataPrep"),
            base_from_sql=base_from_sql,
            base_alias=base_alias,
            alias_by_wt=alias_by_wt,
        )

        from_clause_sql = dp_ctx["from_clause_sql"]
        derived_by_exprid = {
            **dp_ctx.get("derived_by_exprid", {}),
            **dp_ctx.get("computed_alias_by_expr_id", {}),
        }
        derived_by_name = dp_ctx["derived_by_name"]
        rewrite_by_colname = dp_ctx["rewrite_by_colname"]
        rewrite_by_modelid = dp_ctx["rewrite_by_modelid"]
        using_prep = bool(dp_ctx["cte_sql"])

        params: Dict[str, Any] = {}
        param_counter = 0

        def new_param(val: Any) -> str:
            nonlocal param_counter
            param_counter += 1
            key = f"p{param_counter}"
            params[key] = val
            return f":{key}"

        attach_ctx = self._compile_attachments(
            crosswalk_attachments=crosswalk_attachments,
            cohort_attachment=cohort_attachment,
            derived_by_exprid=derived_by_exprid,
            derived_by_name=derived_by_name,
            rewrite_by_colname=rewrite_by_colname,
            rewrite_by_modelid=rewrite_by_modelid,
            using_prep=using_prep,
            base_alias=base_alias,
            alias_by_wt=alias_by_wt,
            plan=plan,
            new_param=new_param,
        )

        derived_by_exprid = {**derived_by_exprid, **attach_ctx.get("exprid_sql", {})}
        def _dedupe_projection_columns(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
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

        def _alias_hint_from_expr(expr_sql: str) -> Optional[str]:
            if not isinstance(expr_sql, str):
                return None
            m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\\.([A-Za-z_][A-Za-z0-9_]*)$", expr_sql)
            return m.group(1) if m else None

        filter_table_ids = self._filter_table_ids(filters, plan)
        sorting_table_ids = self._sorting_table_ids(q.get("sorting") or [], plan)

        raw_cols = q.get("columns") or []
        cols = _dedupe_projection_columns(raw_cols)

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
        output_columns: List[Dict[str, Any]] = []

        def _reserve_output_name(base_name: str | None, alias_hint: Optional[str]) -> str:
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
                raise ServiceError("distinct is not supported with aggregations", status_code=400)
            gb = aggs.get("groupBy") or []
            group_by_exprs = [
                self._col_expr(
                    g,
                    derived_by_exprid,
                    derived_by_name,
                    rewrite_by_colname,
                    rewrite_by_modelid,
                    using_prep,
                    base_alias,
                    alias_by_wt,
                )
                for g in gb
            ]

            for raw_gb, gb_expr in zip(gb, group_by_exprs):
                raw_name = self._col_label_key(raw_gb)
                raw_key = f"{raw_gb.get('workspaceTableId')}:{raw_name}" if isinstance(raw_gb, dict) else raw_name
                user_alias = alias_by_col.get(raw_key)
                alias_hint = None
                if isinstance(raw_gb, dict):
                    wt_id = raw_gb.get("workspaceTableId")
                    if wt_id is not None:
                        try:
                            alias_hint = alias_by_wt.get(int(wt_id))
                        except Exception:
                            alias_hint = None
                alias_hint = alias_hint or _alias_hint_from_expr(gb_expr)
                output_name = _reserve_output_name(user_alias or raw_name, alias_hint)
                select_exprs.append(f"{gb_expr} AS {self._safe_alias(output_name)}")
                output_columns.append({"key": output_name, "label": output_name})

            metric_exprs: List[str] = []
            for m in (aggs.get("metrics") or []):
                fn = (m.get("fn") or "").lower().strip()
                field = m.get("field")
                label = m.get("label")

                metric_sql = self._compile_metric(
                    fn,
                    field,
                    derived_by_exprid,
                    derived_by_name,
                    rewrite_by_colname,
                    rewrite_by_modelid,
                    using_prep,
                    base_alias,
                    alias_by_wt,
                )
                output_name = _reserve_output_name(label or fn or "metric", None)
                metric_sql += f" AS {self._safe_alias(output_name)}"
                metric_exprs.append(metric_sql)
                output_columns.append({"key": output_name, "label": output_name})

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

                expr_sql = self._col_expr(
                    c,
                    derived_by_exprid,
                    derived_by_name,
                    rewrite_by_colname,
                    rewrite_by_modelid,
                    using_prep,
                    base_alias,
                    alias_by_wt,
                )

                alias_hint = None
                if wt_id is not None:
                    try:
                        alias_hint = alias_by_wt_table.get(int(wt_id)) if wt_id is not None else base_alias
                    except Exception:
                        alias_hint = None
                if expr_id and not alias_hint:
                    alias_hint = _alias_hint_from_expr(expr_sql)
                base_output_name = user_alias or desired_name
                if not user_alias and desired_name and name_counts.get(desired_name, 0) > 1:
                    alias_base = alias_hint or base_alias
                    base_output_name = f"{alias_base}_{desired_name}"

                output_name = _reserve_output_name(base_output_name, alias_hint)
                col_expr = f"{expr_sql} AS {self._safe_alias(output_name)}"
                select_exprs.append(col_expr)
                output_columns.append({"key": output_name, "label": output_name})

        if not select_exprs:
            raise ServiceError("No selectable columns/expressions produced.", status_code=400)

        projected_non_primary = projected_table_ids - {primary_id}
        use_two_phase = (
            mode == "preview"
            and bool(filter_only_table_ids)
            and not bool((aggs or {}).get("enabled"))
            and not using_prep
            and not (filter_table_ids & projected_non_primary)
            and sorting_table_ids.issubset({primary_id})
        )

        where_sql, exists_parts = self._compile_where(
            filters,
            derived_by_exprid,
            derived_by_name,
            rewrite_by_colname,
            rewrite_by_modelid,
            using_prep,
            base_alias,
            alias_by_wt,
            plan,
            new_param,
            force_exists_for_tables=filter_only_table_ids if use_two_phase else None,
        )
        if attach_ctx["selects"]:
            if aggs and bool(aggs.get("enabled")):
                raise ServiceError("Attachments with projectFields require non-aggregated queries", status_code=400)
            for expr, out_name in attach_ctx["selects"]:
                # Attachment selects are convenience outputs; skip duplicates already selected by the user.
                if out_name:
                    key = out_name.lower()
                    if output_names.get(key):
                        continue
                    output_names[key] = True
                select_exprs.append(expr)
                if out_name:
                    output_columns.append({"key": out_name, "label": out_name})

        if using_prep and attach_ctx["needs_base_alias"] and from_clause_sql.strip() == "prep":
            from_clause_sql = f"{from_clause_sql} {self._safe_ident(base_alias)}"

        if attach_ctx["joins"]:
            from_clause_sql = f"{from_clause_sql}\n" + "\n".join(attach_ctx["joins"])
        order_sql = self._compile_order_by(
            q.get("sorting") or [],
            derived_by_exprid,
            derived_by_name,
            rewrite_by_colname,
            rewrite_by_modelid,
            using_prep,
            base_alias,
            alias_by_wt,
        )

        select_prefix = "SELECT DISTINCT" if distinct else "SELECT"
        base_where_parts = [
            p
            for p in ([where_sql] if where_sql else []) + (exists_parts or []) + attach_ctx["where"]
            if p
        ]

        base_patients_cte = ""
        base_patients_cte_count = ""
        if use_two_phase:
            patient_id_col = self._safe_ident("patient_id")
            base_patients_cte = (
                "base_patients AS (\n"
                f"  SELECT DISTINCT {self._safe_ident(base_alias)}.{patient_id_col}\n"
                f"  FROM {plan.primary.full_name} {self._safe_ident(base_alias)}\n"
                + (f"  WHERE {' AND '.join(base_where_parts)}\n" if base_where_parts else "")
                + (f"  ORDER BY {order_sql}\n" if order_sql else "")
                + f"  LIMIT {int(limit)}\n"
                + f"  OFFSET {int(offset)}\n"
                + ")"
            )
            base_patients_cte_count = (
                "base_patients AS (\n"
                f"  SELECT DISTINCT {self._safe_ident(base_alias)}.{patient_id_col}\n"
                f"  FROM {plan.primary.full_name} {self._safe_ident(base_alias)}\n"
                + (f"  WHERE {' AND '.join(base_where_parts)}\n" if base_where_parts else "")
                + ")"
            )

            projection_table_ids = (projected_table_ids | attachment_required_table_ids | {primary_id}) - {0}
            projection_from_sql = self._from_clause_from_plan(plan, projection_table_ids)
            projection_lines = projection_from_sql.split("\n")
            join_lines = projection_lines[1:] if len(projection_lines) > 1 else []
            from_clause_sql = (
                f"base_patients bp\n"
                f"JOIN {plan.primary.full_name} {self._safe_ident(base_alias)} "
                f"ON {self._safe_ident(base_alias)}.{patient_id_col} = bp.{patient_id_col}"
            )
            if join_lines:
                from_clause_sql += "\n" + "\n".join(join_lines)

            if attach_ctx["joins"]:
                from_clause_sql = f"{from_clause_sql}\n" + "\n".join(attach_ctx["joins"])

        base_sql = f"{select_prefix} {', '.join(select_exprs)}\nFROM {from_clause_sql}"
        if not use_two_phase:
            if base_where_parts:
                base_sql += f"\nWHERE {' AND '.join(base_where_parts)}"
        if group_by_exprs:
            base_sql += f"\nGROUP BY {', '.join(group_by_exprs)}"

        cte_sql = dp_ctx["cte_sql"]
        if base_patients_cte:
            if cte_sql:
                cte_sql = f"{cte_sql},\n{base_patients_cte}"  # pragma: no cover
            else:
                cte_sql = "WITH " + base_patients_cte
        if attach_ctx["ctes"]:
            if cte_sql:
                cte_sql = f"{cte_sql},\n" + ",\n".join(attach_ctx["ctes"])
            else:
                cte_sql = "WITH " + ",\n".join(attach_ctx["ctes"])

        if cte_sql:
            base_sql = f"{cte_sql}\n{base_sql}"

        if use_two_phase:
            cte_sql_count = dp_ctx["cte_sql"]
            if base_patients_cte_count:
                if cte_sql_count:
                    cte_sql_count = f"{cte_sql_count},\n{base_patients_cte_count}"  # pragma: no cover
                else:
                    cte_sql_count = "WITH " + base_patients_cte_count
            if attach_ctx["ctes"]:
                if cte_sql_count:
                    cte_sql_count = f"{cte_sql_count},\n" + ",\n".join(attach_ctx["ctes"])
                else:
                    cte_sql_count = "WITH " + ",\n".join(attach_ctx["ctes"])  # pragma: no cover
            base_sql_count = f"{select_prefix} {', '.join(select_exprs)}\nFROM {from_clause_sql}"
            if group_by_exprs:
                base_sql_count += f"\nGROUP BY {', '.join(group_by_exprs)}"  # pragma: no cover
            if cte_sql_count:
                base_sql_count = f"{cte_sql_count}\n{base_sql_count}"
            count_sql = f"SELECT COUNT(*) AS total FROM (\n{base_sql_count}\n) q"
        else:
            count_sql = f"SELECT COUNT(*) AS total FROM (\n{base_sql}\n) q"

        sql = base_sql
        if order_sql:
            sql += f"\nORDER BY {order_sql}"

        if mode == "preview" and not use_two_phase:
            sql += f"\nLIMIT {int(limit)}\nOFFSET {int(offset)}"

        return CompiledQuery(sql=sql, count_sql=count_sql, params=params, output_columns=output_columns)

    # -----------------------------
    # Data Prep compilation (CTE)
    # -----------------------------
    def _compile_data_prep_cte(
        self,
        data_prep: Any,
        base_from_sql: str,
        base_alias: str,
        alias_by_wt: Dict[int, str],
    ) -> Dict[str, Any]:
        default_from = base_from_sql

        if not data_prep or not isinstance(data_prep, dict):
            return {
                "cte_sql": "",
                "from_clause_sql": default_from,
                "derived_by_exprid": {},
                "computed_alias_by_expr_id": {},
                "derived_by_name": {},
                "rewrite_by_colname": {},
                "rewrite_by_modelid": {},
            }

        rules = data_prep.get("rules") or []
        if not isinstance(rules, list) or not rules:
            return {
                "cte_sql": "",
                "from_clause_sql": default_from,
                "derived_by_exprid": {},
                "computed_alias_by_expr_id": {},
                "derived_by_name": {},
                "rewrite_by_colname": {},
                "rewrite_by_modelid": {},
            }

        derived_by_exprid: Dict[str, str] = {}
        computed_alias_by_expr_id: Dict[str, str] = {}
        derived_by_name: Dict[str, str] = {}
        rewrite_by_colname: Dict[str, str] = {}
        rewrite_by_modelid: Dict[int, str] = {}

        exprs: List[str] = []
        using_prep = False  # compiling inside CTE against src

        def normalize_date_format(fmt: Any) -> Optional[str]:
            if fmt is None:
                return None
            if not isinstance(fmt, str):
                raise ServiceError("parse_date.format must be string or null", status_code=400)
            s = fmt.strip()
            if s.startswith("(") and s.endswith(")"):
                s = s[1:-1].strip()
            if not s:
                return None
            return s.lower()

        for i, r in enumerate(rules):
            if not isinstance(r, dict):
                raise ServiceError(f"dataPrep.rules[{i}] must be an object", status_code=400)

            op = (r.get("op") or "").strip()
            rid = r.get("id")
            if not rid or not isinstance(rid, str):
                raise ServiceError(f"dataPrep.rules[{i}].id is required", status_code=400)

            target = r.get("target")
            output = r.get("output")
            if not isinstance(output, dict):
                raise ServiceError(f"dataPrep.rules[{i}].output must be a column key", status_code=400)
            if op != "concat" and not isinstance(target, dict):
                raise ServiceError(f"dataPrep.rules[{i}].target must be a column key", status_code=400)

            out_name = output.get("columnName")
            if not out_name or not isinstance(out_name, str):
                raise ServiceError(f"dataPrep.rules[{i}].output.columnName is required", status_code=400)

            # ✅ Always use an internal identifier to avoid collisions with SELECT *
            out_ident = self._dp_ident(out_name)

            target_expr = None
            if op != "concat":
                target_expr = self._col_expr(
                    target,
                    derived_by_exprid,
                    derived_by_name,
                    rewrite_by_colname,
                    rewrite_by_modelid,
                    using_prep,
                    base_alias,
                    alias_by_wt,
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
                        using_prep,
                        base_alias,
                        alias_by_wt,
                    )
                    expr = f"COALESCE({base}, {fb_expr})"
                else:
                    expr = f"COALESCE({base}, {self._literal_sql(val)})"

                exprs.append(f"{expr} AS {out_ident}")

            elif op == "cast":
                to_type = r.get("toType")
                if not to_type or not isinstance(to_type, str):
                    raise ServiceError("cast.toType is required", status_code=400)
                safe = bool(r.get("safe"))
                if safe:
                    exprs.append(f"TRY_CAST({target_expr} AS {to_type}) AS {out_ident}")
                else:
                    exprs.append(f"CAST({target_expr} AS {to_type}) AS {out_ident}")

            elif op == "normalize_text":
                mode = r.get("mode")
                if mode not in ("lower", "upper", "trim", "trim_lower"):
                    raise ServiceError("normalize_text.mode invalid", status_code=400)
                if mode == "lower":
                    exprs.append(f"LOWER({target_expr}) AS {out_ident}")
                elif mode == "upper":
                    exprs.append(f"UPPER({target_expr}) AS {out_ident}")
                elif mode == "trim":
                    exprs.append(f"TRIM({target_expr}) AS {out_ident}")
                else:
                    exprs.append(f"LOWER(TRIM({target_expr})) AS {out_ident}")

            elif op == "parse_date":
                fmt = normalize_date_format(r.get("format", None))
                if fmt:
                    exprs.append(f"TO_DATE({target_expr}, {self._literal_sql(fmt)}) AS {out_ident}")
                else:
                    exprs.append(f"TO_DATE({target_expr}) AS {out_ident}")

            elif op == "date_part":
                part = (r.get("part") or "").strip().lower()
                if part not in ("year", "month", "day"):
                    raise ServiceError("date_part.part must be year|month|day", status_code=400)
                fn = part.upper()
                # Use YEAR/MONTH/DAY to compare numerically instead of DATE = '2024' string comparisons.
                exprs.append(f"{fn}({target_expr}) AS {out_ident}")

            elif op == "round":
                dec = r.get("decimals")
                if dec is None or not isinstance(dec, int):
                    raise ServiceError("round.decimals must be an integer", status_code=400)
                exprs.append(f"ROUND({target_expr}, {int(dec)}) AS {out_ident}")

            elif op == "concat":
                inputs = r.get("inputs")
                if not isinstance(inputs, list) or not inputs:
                    raise ServiceError("concat.inputs must be a non-empty list", status_code=400)

                separator = r.get("separator")
                if separator is None:
                    separator = ""
                if not isinstance(separator, str):
                    raise ServiceError("concat.separator must be a string or null", status_code=400)
                sep_sql = self._literal_sql(separator)

                nulls_mode = (r.get("nulls") or "skip").strip().lower()
                if nulls_mode not in ("skip", "propagate", "empty"):
                    raise ServiceError("concat.nulls must be skip|propagate|empty", status_code=400)

                parts: List[str] = []
                for j, ref in enumerate(inputs):
                    if not isinstance(ref, dict):
                        raise ServiceError(f"concat.inputs[{j}] must be an object", status_code=400)
                    ref_type = (ref.get("type") or "").strip().lower()
                    if ref_type == "column":
                        expr = self._col_expr(
                            ref.get("col"),
                            derived_by_exprid,
                            derived_by_name,
                            rewrite_by_colname,
                            rewrite_by_modelid,
                            using_prep,
                            base_alias,
                            alias_by_wt,
                        )
                    elif ref_type == "literal":
                        expr = self._literal_sql(ref.get("value"))
                    else:
                        raise ServiceError("concat.inputs type must be column or literal", status_code=400)

                    if nulls_mode == "empty":
                        expr = f"COALESCE({expr}, '')"
                    parts.append(expr)

                if nulls_mode == "skip":
                    expr_sql = f"CONCAT_WS({sep_sql}, {', '.join(parts)})"
                else:
                    if separator:
                        interleaved: List[str] = []
                        for idx, part in enumerate(parts):
                            if idx:
                                interleaved.append(sep_sql)
                            interleaved.append(part)
                        expr_sql = f"CONCAT({', '.join(interleaved)})"
                    else:
                        expr_sql = f"CONCAT({', '.join(parts)})"
                exprs.append(f"{expr_sql} AS {out_ident}")

            else:
                raise ServiceError(f"Unsupported dataPrep op: {op}", status_code=400)

            derived_by_exprid[rid] = out_ident
            out_expr_id = output.get("exprId")
            if out_expr_id and isinstance(out_expr_id, str):
                computed_alias_by_expr_id[out_expr_id] = out_ident
            derived_by_name[out_name] = out_ident

            # ✅ query-wide rewrite: target -> internal output identifier
            if isinstance(target, dict):
                tgt_name = target.get("columnName")
                if isinstance(tgt_name, str) and tgt_name:
                    rewrite_by_colname[tgt_name] = out_ident

                tgt_id = target.get("modelColumnId")
                if isinstance(tgt_id, int):
                    rewrite_by_modelid[tgt_id] = out_ident

        if not exprs:
            return {
                "cte_sql": "",
                "from_clause_sql": default_from,
                "derived_by_exprid": {},
                "computed_alias_by_expr_id": {},
                "derived_by_name": {},
                "rewrite_by_colname": {},
                "rewrite_by_modelid": {},
            }

        cte_sql = (
            "WITH prep AS (\n"
            "  SELECT *,\n"
            f"    {',\n    '.join(exprs)}\n"
            f"  FROM {default_from}\n"
            ")"
        )

        return {
            "cte_sql": cte_sql,
            "from_clause_sql": "prep",
            "derived_by_exprid": derived_by_exprid,
            "computed_alias_by_expr_id": computed_alias_by_expr_id,
            "derived_by_name": derived_by_name,
            "rewrite_by_colname": rewrite_by_colname,
            "rewrite_by_modelid": rewrite_by_modelid,
        }

    def _from_clause_from_plan(self, plan: DomainPlan, required_table_ids: set[int]) -> str:
        tables_by_id = {t.workspace_table_id: t for t in plan.tables}
        needed_edges: Dict[str, bool] = {}
        for wt_id in required_table_ids:
            if int(wt_id) == int(plan.primary.workspace_table_id):
                continue
            for edge in self._domains.get_join_path(plan, int(wt_id)):
                needed_edges[str(edge.join_id)] = True

        joined = {plan.primary.workspace_table_id}
        clauses = [f"{plan.primary.full_name} {self._safe_ident(plan.primary.alias)}"]

        for edge in plan.joins:
            if str(edge.join_id) not in needed_edges:
                continue
            if edge.from_workspace_table_id == edge.to_workspace_table_id:
                raise ServiceError("Join cannot reference the same table", status_code=400)
            if edge.from_workspace_table_id not in tables_by_id or edge.to_workspace_table_id not in tables_by_id:
                raise ServiceError("Join references table not in domain", status_code=400)
            if edge.from_workspace_table_id not in joined:
                raise ServiceError("Join order invalid: from table not yet joined", status_code=400)

            join_type = (edge.join_type or "").upper()
            if join_type not in {"INNER", "LEFT", "RIGHT"}:
                raise ServiceError(f"Invalid join_type: {join_type}", status_code=400)

            to_table = tables_by_id[edge.to_workspace_table_id]
            on_sql = self._compile_join_on(edge, plan.alias_by_workspace_table_id)
            clauses.append(
                f"{join_type} JOIN {to_table.full_name} {self._safe_ident(to_table.alias)} ON {on_sql}"
            )
            joined.add(edge.to_workspace_table_id)

        missing = [t.workspace_table_id for t in plan.tables if t.workspace_table_id in required_table_ids and t.workspace_table_id not in joined]
        if missing:
            raise ServiceError("Domain join plan does not cover all tables", status_code=400)

        return "\n".join(clauses)

    def _compile_join_on(self, edge: Any, alias_by_wt: Dict[int, str]) -> str:
        from_alias = alias_by_wt.get(int(edge.from_workspace_table_id))
        to_alias = alias_by_wt.get(int(edge.to_workspace_table_id))
        if not from_alias or not to_alias:
            raise ServiceError("Join references table not in domain", status_code=400)

        return " AND ".join(self._join_predicates(edge, from_alias, to_alias))

    def _join_predicates(self, edge: Any, from_alias: str, to_alias: str) -> List[str]:
        spec = edge.join_spec or {}
        on_list = spec.get("on") or []
        if not isinstance(on_list, list) or not on_list:
            raise ServiceError("Join spec must include non-empty on[]", status_code=400)

        preds = []
        for item in on_list:
            if not isinstance(item, dict):
                raise ServiceError("Join spec on[] must be objects", status_code=400)

            left = item.get("left") or {}
            right = item.get("right") or {}

            left_wt = left.get("workspaceTableId")
            right_wt = right.get("workspaceTableId")
            if left_wt is not None and int(left_wt) != int(edge.from_workspace_table_id):
                raise ServiceError("Join spec left.workspaceTableId must match from table", status_code=400)
            if right_wt is not None and int(right_wt) != int(edge.to_workspace_table_id):
                raise ServiceError("Join spec right.workspaceTableId must match to table", status_code=400)

            left_expr = self._compile_join_side(left, expected_scope="from", alias=from_alias)
            right_expr = self._compile_join_side(right, expected_scope="to", alias=to_alias)

            preds.append(f"{left_expr} = {right_expr}")

        return preds

    def _compile_join_side(self, side: Dict[str, Any], *, expected_scope: str, alias: str) -> str:
        expr = side.get("expr")
        if expr:
            scope, col, key = self._parse_join_expr(expr)
            if scope != expected_scope:
                raise ServiceError("Join spec expr uses wrong table scope", status_code=400)
            return f"get_json_object({self._safe_ident(alias)}.{self._safe_ident(col)}, '$.{key}')"

        col = side.get("columnName") or side.get("col")
        if not col or not isinstance(col, str) or "." in col:
            raise ServiceError("Join spec column invalid", status_code=400)
        return f"{self._safe_ident(alias)}.{self._safe_ident(col)}"

    def _parse_join_expr(self, expr: str) -> tuple[str, str, str]:
        pattern = r"^get_json_object\(\{(from|to)\}\.([A-Za-z0-9_]+),\s*'\$\.([A-Za-z0-9_]+)'\)$"
        match = re.match(pattern, expr)
        if not match:
            raise ServiceError(
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
        raise ServiceError("workspaceTableId is not in domain", status_code=400)

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

    def _render_sql_with_params(self, sql: str, params: Dict[str, Any]) -> str:
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
    def _safe_ident(self, s: str) -> str:
        if not s or not isinstance(s, str) or not self._IDENT_RE.match(s):
            raise ServiceError(f"Invalid identifier: {s}", status_code=400)
        return s

    def _safe_table_full_name(self, name: str) -> str:
        if not name or not isinstance(name, str):
            raise ServiceError("Invalid table name", status_code=400)
        parts = [p.strip() for p in name.split(".") if p.strip()]
        if not parts:
            raise ServiceError("Invalid table name", status_code=400)
        return ".".join(f"`{self._safe_ident(p)}`" for p in parts)

    def _safe_alias(self, s: str) -> str:
        if s is None or not isinstance(s, str):
            raise ServiceError("Invalid alias", status_code=400)

        v = s.strip()
        if not v:
            raise ServiceError("Invalid alias", status_code=400)

        if self._IDENT_RE.match(v):
            return v

        if any(ord(ch) < 32 for ch in v):
            raise ServiceError("Invalid alias (control characters)", status_code=400)

        v = v.replace("`", "``")
        return f"`{v}`"

    def _dp_ident(self, out_name: str) -> str:
        """
        Internal DP column identifier, guaranteed safe and collision-resistant.
        Example: out_name="claim type" -> "__dp_claim_type"
        """
        base = re.sub(r"[^A-Za-z0-9_]+", "_", (out_name or "").strip())
        if not base:
            base = "col"
        # ensure doesn't start with a digit
        if base[0].isdigit():
            base = f"c_{base}"
        return self._safe_ident(f"__dp_{base}")

    def _resolve_cohort_view_name(self, cohort_id: Any) -> str:
        cid = str(cohort_id or "").strip()
        if not cid:
            raise ServiceError("cohortId is required", status_code=400)

        sql = "SELECT sql_json FROM saved_query WHERE id = :qid"
        params: Dict[str, Any] = {"qid": cid}
        ws_id = getattr(self._domains, "_workspace_id", None)
        if ws_id:
            sql += " AND workspace_id = :ws"
            params["ws"] = ws_id

        rows = MySQLSQLExecutor().execute_query_mappings(sql, params)
        if not rows:
            raise ServiceError("Cohort view not found", status_code=404)

        parsed = self._parse_sql_json(rows[0].get("sql_json"))
        view_name = None
        if isinstance(parsed, dict):
            meta = parsed.get("meta")
            if isinstance(meta, dict):
                view_name = meta.get("viewName") or meta.get("view_name")
            if not view_name:
                view_name = parsed.get("viewName")

        view_name = str(view_name).strip() if view_name else ""
        if not view_name:
            raise ServiceError("Cohort view name not available; provide viewName", status_code=400)
        return view_name

    def _parse_sql_json(self, sql_json: Any) -> Dict[str, Any] | None:
        if not sql_json:
            return None
        if isinstance(sql_json, str):
            try:
                sql_json = json.loads(sql_json)
            except Exception:
                return None
        return sql_json if isinstance(sql_json, dict) else None

    def _project_expr(self, expr: str, desired_name: str | None, user_alias: str | None) -> str:
        """
        When we rewrite to internal dp columns (e.g. __dp_claim_type), project back to the
        expected user-facing name unless user_alias is provided.
        """
        if user_alias:
            return f"{expr} AS {self._safe_alias(user_alias)}"
        if desired_name and isinstance(desired_name, str) and desired_name.strip():
            if expr != desired_name and expr.startswith("__dp_"):
                return f"{expr} AS {self._safe_ident(desired_name)}"
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
        using_prep: bool,
        base_alias: str,
        alias_by_wt: Dict[int, str],
    ) -> str:
        # legacy string
        if isinstance(key_or_ref, str):
            cn = key_or_ref.strip()
            if "." in cn:
                raise ServiceError(f"Qualified column names are not allowed: {cn}", status_code=400)

            if using_prep and cn in rewrite_by_colname:
                return rewrite_by_colname[cn]

            return self._physical_col_expr(cn, using_prep=using_prep, base_alias=base_alias, alias=None)

        if not isinstance(key_or_ref, dict):
            raise ServiceError("Invalid column reference", status_code=400)

        expr_id = key_or_ref.get("exprId")
        cn = key_or_ref.get("columnName")
        mid = key_or_ref.get("modelColumnId")
        wt_id = key_or_ref.get("workspaceTableId")

        if expr_id and expr_id in derived_by_exprid:
            return derived_by_exprid[expr_id]

        if cn and cn in derived_by_name:
            return derived_by_name[cn]

        if not cn or not isinstance(cn, str):
            raise ServiceError("Invalid columnName", status_code=400)
        if "." in cn:
            raise ServiceError(f"Qualified column names are not allowed: {cn}", status_code=400)

        if using_prep:
            if isinstance(mid, int) and mid in rewrite_by_modelid:
                return rewrite_by_modelid[mid]
            if cn in rewrite_by_colname:
                return rewrite_by_colname[cn]

        alias = None
        if wt_id is not None:
            try:
                wt_id_int = int(wt_id)
            except Exception:
                raise ServiceError("Invalid workspaceTableId", status_code=400)
            alias = alias_by_wt.get(wt_id_int)
            if not alias:
                raise ServiceError("workspaceTableId is not in domain", status_code=400)

        return self._physical_col_expr(cn, using_prep=using_prep, base_alias=base_alias, alias=alias)

    def _physical_col_expr(self, col_name: str, using_prep: bool, base_alias: str, alias: str | None) -> str:
        if not col_name or not isinstance(col_name, str):
            raise ServiceError("Invalid columnName", status_code=400)
        if "." in col_name:
            raise ServiceError(f"Qualified column names are not allowed: {col_name}", status_code=400)

        if using_prep:
            return self._safe_ident(col_name)

        base = alias or base_alias
        return f"{self._safe_ident(base)}.{self._safe_ident(col_name)}"

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
        using_prep: bool,
        base_alias: str,
        alias_by_wt: Dict[int, str],
    ) -> str:
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
                using_prep,
                base_alias,
                alias_by_wt,
            )
            return f"COUNT({col})"

        if fn == "count_distinct":
            if not field:
                raise ServiceError("count_distinct requires a field", status_code=400)
            col = self._col_expr(
                field,
                derived_by_exprid,
                derived_by_name,
                rewrite_by_colname,
                rewrite_by_modelid,
                using_prep,
                base_alias,
                alias_by_wt,
            )
            return f"COUNT(DISTINCT {col})"

        if fn in ("sum", "avg", "min", "max"):
            if not field:
                raise ServiceError(f"{fn} requires a field", status_code=400)
            return f"{fn.upper()}({self._col_expr(field, derived_by_exprid, derived_by_name, rewrite_by_colname, rewrite_by_modelid, using_prep, base_alias, alias_by_wt)})"

        if fn.replace("_", " ").upper() in ("COUNT DISTINCT", "COUNT", "SUM", "AVG", "MIN", "MAX"):
            legacy = fn.replace("_", " ").upper()
            if legacy == "COUNT":
                return "COUNT(*)" if not field else f"COUNT({self._col_expr(field, derived_by_exprid, derived_by_name, rewrite_by_colname, rewrite_by_modelid, using_prep, base_alias, alias_by_wt)})"
            if legacy == "COUNT DISTINCT":
                if not field:
                    raise ServiceError("count_distinct requires a field", status_code=400)
                return f"COUNT(DISTINCT {self._col_expr(field, derived_by_exprid, derived_by_name, rewrite_by_colname, rewrite_by_modelid, using_prep, base_alias, alias_by_wt)})"
            if legacy in ("SUM", "AVG", "MIN", "MAX"):
                if not field:
                    raise ServiceError(f"{legacy} requires a field", status_code=400)
                return f"{legacy}({self._col_expr(field, derived_by_exprid, derived_by_name, rewrite_by_colname, rewrite_by_modelid, using_prep, base_alias, alias_by_wt)})"

        raise ServiceError(f"Unsupported metric fn: {fn}", status_code=400)

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
        using_prep: bool,
        base_alias: str,
        alias_by_wt: Dict[int, str],
        plan: DomainPlan,
        new_param: Callable[[Any], str],
        force_exists_for_tables: Optional[set[int]] = None,
    ) -> Tuple[str, List[str]]:
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

        def compile_in_list(field_expr: str, values: List[Any]) -> str:
            if not values:
                return ""
            if len(values) > MAX_MANUAL_IN:
                raise ServiceError(
                    "Too many IN values; upload a list/crosswalk instead",
                    status_code=400,
                )
            expr = f"{field_expr} IN ({', '.join(new_param(v) for v in values)})"
            if len(values) > 200:
                expr = f"{expr} -- normalized large IN list ({len(values)} items)"
            return expr

        def compile_condition_expr(field_expr: str, op: str, value: Any) -> str:
            if op == "equals":
                return f"{field_expr} = {new_param(value)}"
            if op == "contains":
                return f"{field_expr} LIKE {new_param(f'%{value}%')}"
            if op == "starts_with":
                return f"{field_expr} LIKE {new_param(f'{value}%')}"
            if op == "gt":
                return f"{field_expr} > {new_param(value)}"
            if op == "lt":
                return f"{field_expr} < {new_param(value)}"
            if op == "in":
                if isinstance(value, dict) and value.get("mode"):
                    mode = value.get("mode")
                    if mode == "manual":
                        vals = _normalize_in_values(value.get("values"))
                        return compile_in_list(field_expr, vals)
                    if mode == "cohort":
                        view_name = value.get("viewName") or self._resolve_cohort_view_name(value.get("cohortId"))
                        view_sql = self._safe_table_full_name(view_name)
                        return f"{field_expr} IN (SELECT {self._safe_ident('patient_id')} FROM {view_sql})"
                    if mode == "crosswalk":
                        list_type = value.get("listType")
                        list_id = value.get("listId")
                        if not list_type or list_type not in CROSSWALK_IN_COLUMN_BY_TYPE:
                            raise ServiceError("Invalid crosswalk listType for IN filter", status_code=400)
                        if not list_id:
                            raise ServiceError("crosswalk IN requires listId", status_code=400)
                        table = TABLE_BY_TYPE.get(list_type)
                        if not table:
                            raise ServiceError("Invalid crosswalk listType for IN filter", status_code=400)
                        col = CROSSWALK_IN_COLUMN_BY_TYPE[list_type]
                        table_sql = self._safe_table_full_name(table)
                        return (
                            f"{field_expr} IN (SELECT {self._safe_ident(col)} "
                            f"FROM {table_sql} WHERE list_id = {new_param(list_id)})"
                        )
                    raise ServiceError("Unsupported IN mode", status_code=400)

                vals = _normalize_in_values(value)
                return compile_in_list(field_expr, vals)
            if op == "between":
                if not isinstance(value, list) or len(value) != 2:
                    raise ServiceError("between requires [min,max]", status_code=400)
                return f"{field_expr} BETWEEN {new_param(value[0])} AND {new_param(value[1])}"
            raise ServiceError(f"Unsupported filter op: {op}", status_code=400)

        def field_expr_for_exists(field: Any, sub_alias: str) -> str:
            if isinstance(field, str):
                cn = field.strip()
            elif isinstance(field, dict):
                cn = (field.get("columnName") or "").strip()
            else:
                cn = ""

            if not cn or "." in cn:
                raise ServiceError("Invalid columnName for exists filter", status_code=400)

            return f"{self._safe_ident(sub_alias)}.{self._safe_ident(cn)}"

        def render_exists(group_key: str, group_info: Dict[str, Any]) -> str:
            nonlocal exists_counter
            exists_counter += 1
            sub_alias = f"e{exists_counter}"

            target_id = int(group_info["workspace_table_id"])
            path = self._domains.get_join_path(plan, target_id)

            tables_by_id = {t.workspace_table_id: t for t in plan.tables}
            if not path:
                raise ServiceError("EXISTS requires non-primary table", status_code=400)

            first_edge = path[0]
            first_to = int(first_edge.to_workspace_table_id)
            from_alias = plan.primary.alias
            to_alias = sub_alias

            first_table = tables_by_id.get(first_to)
            if not first_table:
                raise ServiceError("Join path invalid for EXISTS", status_code=400)

            join_clauses = [f"{first_table.full_name} {self._safe_ident(to_alias)}"]

            where_preds: List[str] = []
            where_preds.extend(self._join_predicates(first_edge, from_alias, to_alias))

            current_alias = to_alias
            current_id = first_to

            for edge in path[1:]:
                if int(edge.from_workspace_table_id) != int(current_id):
                    raise ServiceError("Join path invalid for EXISTS", status_code=400)
                next_id = int(edge.to_workspace_table_id)
                next_table = tables_by_id.get(next_id)
                if not next_table:
                    raise ServiceError("Join path invalid for EXISTS", status_code=400)
                next_alias = f"{sub_alias}_{next_id}"
                join_clauses.append(
                    f"JOIN {next_table.full_name} {self._safe_ident(next_alias)} "
                    f"ON {' AND '.join(self._join_predicates(edge, current_alias, next_alias))}"
                )
                current_alias = next_alias
                current_id = next_id

            pred_sqls = []
            for cond in group_info["predicates"]:
                field_expr = field_expr_for_exists(cond["field"], current_alias)
                pred_sqls.append(compile_condition_expr(field_expr, cond["op"], cond["value"]))

            all_where = [p for p in where_preds + pred_sqls if p]
            if not all_where:
                raise ServiceError("EXISTS predicates missing", status_code=400)

            subquery = (
                "SELECT 1\n"
                f"FROM {' '.join(join_clauses)}\n"
                f"WHERE {' AND '.join(all_where)}"
            )
            return f"EXISTS (\n{subquery}\n)"

        def walk(n: Any) -> Tuple[str, Dict[str, Any]]:
            if not isinstance(n, dict):
                raise ServiceError("Invalid filter node", status_code=400)

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
                                    raise ServiceError("existsScopeId must not mix tables", status_code=400)
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
                    raise ServiceError("Virtual expr fields cannot be EXISTS filters", status_code=500)  # pragma: no cover

                op = n.get("op")
                value = n.get("value")

                if mode == "WHERE":
                    if isinstance(field, str):
                        if "." in field:
                            raise ServiceError(f"Qualified column names are not allowed in filters: {field}", status_code=400)
                        if using_prep and field in rewrite_by_colname:
                            field_expr = rewrite_by_colname[field]
                        else:
                            field_expr = self._physical_col_expr(field, using_prep=using_prep, base_alias=base_alias, alias=None)
                    else:
                        field_expr = self._col_expr(
                            field,
                            derived_by_exprid,
                            derived_by_name,
                            rewrite_by_colname,
                            rewrite_by_modelid,
                            using_prep,
                            base_alias,
                            alias_by_wt,
                        )
                    return compile_condition_expr(field_expr, op, value), {}

                if mode == "EXISTS":
                    key = n.get("existsScopeId") or str(wt_id)
                    return "", {
                        str(key): {
                            "workspace_table_id": int(wt_id),
                            "predicates": [{"field": field, "op": op, "value": value}],
                        }
                    }

                raise ServiceError("Invalid filter mode", status_code=400)

            raise ServiceError("Invalid filter node type", status_code=400)

        where_sql, exists_groups = walk(node)
        exists_parts = [render_exists(k, v) for k, v in exists_groups.items()]
        return where_sql, exists_parts

    def _compile_attachments(
        self,
        *,
        crosswalk_attachments: List[Any],
        cohort_attachment: Optional[Dict[str, Any]],
        derived_by_exprid: Dict[str, str],
        derived_by_name: Dict[str, str],
        rewrite_by_colname: Dict[str, str],
        rewrite_by_modelid: Dict[int, str],
        using_prep: bool,
        base_alias: str,
        alias_by_wt: Dict[int, str],
        plan: DomainPlan,
        new_param: Callable[[Any], str],
    ) -> Dict[str, Any]:
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
            norm = self._normalize_col_key(col_key, path)
            expr = self._col_expr(
                norm,
                derived_by_exprid,
                derived_by_name,
                rewrite_by_colname,
                rewrite_by_modelid,
                using_prep,
                base_alias,
                alias_by_wt,
            )
            if using_prep and isinstance(expr, str) and self._IDENT_RE.match(expr):
                needs_base_alias = True
                expr = f"{self._safe_ident(base_alias)}.{expr}"
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

        for i, cw in enumerate(crosswalk_attachments or []):
            if not isinstance(cw, dict):
                raise ServiceError("crosswalks entries must be objects", status_code=400)
            mode = (cw.get("mode") or "").strip().lower()
            if mode not in ("filter", "join"):
                raise ServiceError("crosswalk mode must be filter or join", status_code=400)

            list_type = cw.get("listType")
            list_id = cw.get("listId")
            if list_type not in CROSSWALK_KEY_BY_TYPE:
                raise ServiceError("Invalid crosswalk listType", status_code=400)
            if not list_id:
                raise ServiceError("crosswalk listId is required", status_code=400)
            if not workspace_id:
                raise ServiceError("workspace_id is required for crosswalks", status_code=400)

            cols = cw.get("domainJoinColumns") or []
            if not isinstance(cols, list):
                raise ServiceError(f"crosswalks[{i}].domainJoinColumns must be a list", status_code=400)
            if not cols:
                raise ServiceError("crosswalks requires domainJoinColumns", status_code=400)

            domain_exprs = [domain_col_expr(col, f"crosswalks[{i}].domainJoinColumns[{j}]") for j, col in enumerate(cols)]

            key_col = CROSSWALK_KEY_BY_TYPE[list_type]
            table = TABLE_BY_TYPE.get(list_type)
            if not table:
                raise ServiceError("Invalid crosswalk listType", status_code=400)
            table_sql = self._safe_table_full_name(table)

            ws_param = new_param(workspace_id)
            list_param = new_param(list_id)

            def active_pred(alias: Optional[str]) -> str:
                prefix = f"{self._safe_ident(alias)}." if alias else ""
                return (
                    f"{prefix}workspace_id = {ws_param} "
                    f"AND {prefix}list_id = {list_param} "
                    f"AND ({prefix}expiration_date IS NULL OR {prefix}expiration_date >= current_date())"
                )

            if mode == "filter":
                cw_alias = "cw"
                join_pred = " OR ".join(
                    f"{self._safe_ident(cw_alias)}.{self._safe_ident(key_col)} = {expr}" for expr in domain_exprs
                )
                if len(domain_exprs) > 1:
                    join_pred = f"({join_pred})"
                exists_sql = (
                    "EXISTS (\n"
                    f"SELECT 1 FROM {table_sql} {self._safe_ident(cw_alias)}\n"
                    f"WHERE {active_pred(cw_alias)} AND {join_pred}\n"
                    ")"
                )
                where.append(exists_sql)
                continue

            cte_base = CROSSWALK_JOIN_ALIAS_BY_TYPE[list_type]
            cte_name = unique_cte_name(cte_base)

            agg_fields = ", ".join(
                f"MAX({self._safe_ident(f)}) AS {self._safe_ident(f)}" for f in CROSSWALK_FIELDS_BY_TYPE[list_type]
            )
            cte_sql = (
                f"{self._safe_ident(cte_name)} AS (\n"
                f"  SELECT workspace_id, list_id, {self._safe_ident(key_col)}, {agg_fields}\n"
                f"  FROM {table_sql}\n"
                f"  WHERE {active_pred(None)}\n"
                f"  GROUP BY workspace_id, list_id, {self._safe_ident(key_col)}\n"
                ")"
            )
            ctes.append(cte_sql)

            project_fields = cw.get("projectFields") or []
            if not isinstance(project_fields, list):
                raise ServiceError("crosswalk projectFields must be a list", status_code=400)
            allowed = set(CROSSWALK_FIELDS_BY_TYPE[list_type])
            for field in project_fields:
                if field not in allowed:
                    raise ServiceError("Invalid crosswalk project field", status_code=400)

            att_id = (cw.get("id") or f"cw{i+1}")

            separate = bool(cw.get("supportsSeparateAliasJoins") or cw.get("separateAliasJoins"))
            if list_type == "npiCategories" and project_fields and separate and len(domain_exprs) > 1:
                for j, (col_key, expr) in enumerate(zip(cols, domain_exprs)):
                    suffix = join_alias_suffix(col_key, j + 1)
                    join_alias = self._safe_ident(f"{cte_name}_{suffix}")
                    joins.append(
                        f"JOIN {self._safe_ident(cte_name)} {join_alias} "
                        f"ON {join_alias}.{self._safe_ident(key_col)} = {expr}"
                    )
                    for field in project_fields:
                        out_name = f"cw_{suffix}_{field}"
                        expr_sql = f"{join_alias}.{self._safe_ident(field)} AS {self._safe_alias(out_name)}"
                        selects.append((expr_sql, out_name))
                        exprid_sql[f"cw:{att_id}:cw:{suffix}:{field}"] = f"{join_alias}.{self._safe_ident(field)}"
                continue

            join_alias = self._safe_ident(cte_name)
            on_pred = " OR ".join(
                f"{join_alias}.{self._safe_ident(key_col)} = {expr}" for expr in domain_exprs
            )
            if len(domain_exprs) > 1:
                on_pred = f"({on_pred})"
            joins.append(f"JOIN {self._safe_ident(cte_name)} {join_alias} ON {on_pred}")

            for field in project_fields:
                out_name = CROSSWALK_PROJECT_ALIASES_BY_TYPE[list_type].get(field) or f"cw_{field}"
                expr_sql = f"{join_alias}.{self._safe_ident(field)} AS {self._safe_alias(out_name)}"
                selects.append((expr_sql, out_name))
                exprid_sql[f"cw:{att_id}:cw:{field}"] = f"{join_alias}.{self._safe_ident(field)}"

        if cohort_attachment:
            if not isinstance(cohort_attachment, dict):
                raise ServiceError("cohortJoin must be an object", status_code=400)
            mode = (cohort_attachment.get("mode") or "").strip().lower()
            if mode not in ("filter", "join"):
                raise ServiceError("cohortJoin.mode must be filter or join", status_code=400)

            table_name = cohort_attachment.get("cohortTableFullName")
            if not table_name or not isinstance(table_name, str):
                raise ServiceError("cohortTableFullName is required", status_code=400)
            table_sql = self._safe_table_full_name(table_name)

            alias = cohort_attachment.get("cohortTableAlias") or "cohort"
            alias = self._safe_ident(str(alias))

            join_key = cohort_attachment.get("cohortJoinKey")
            if not join_key or not isinstance(join_key, str):
                raise ServiceError("cohortJoinKey is required", status_code=400)
            join_key = self._safe_ident(join_key)

            domain_col = cohort_attachment.get("domainJoinColumn")
            if domain_col is None:
                raise ServiceError("cohortJoin.domainJoinColumn is required", status_code=400)
            domain_expr = domain_col_expr(domain_col, "cohortJoin.domainJoinColumn")

            cohort_key_filter = cohort_attachment.get("cohortKeyFilter")
            cohort_att_id = (cohort_attachment.get("id") or "cohort")

            if mode == "filter":
                preds = [f"{alias}.{join_key} = {domain_expr}"]
                if cohort_key_filter is not None:
                    preds.append(f"{alias}.{self._safe_ident('cohort_key')} = {new_param(cohort_key_filter)}")
                exists_sql = f"EXISTS (SELECT 1 FROM {table_sql} {alias} WHERE {' AND '.join(preds)})"
                where.append(exists_sql)
            else:
                cte_base = "cohort" if alias == "cohort" else f"cohort_{alias}"
                cte_name = unique_cte_name(cte_base)
                where_sql = ""
                if cohort_key_filter is not None:
                    where_sql = f" WHERE {self._safe_ident('cohort_key')} = {new_param(cohort_key_filter)}"
                ctes.append(f"{self._safe_ident(cte_name)} AS (SELECT * FROM {table_sql}{where_sql})")
                joins.append(
                    f"JOIN {self._safe_ident(cte_name)} {alias} ON {alias}.{join_key} = {domain_expr}"
                )

                project_fields = cohort_attachment.get("projectFields") or []
                if not isinstance(project_fields, list):
                    raise ServiceError("cohortJoin.projectFields must be a list", status_code=400)
                prefix = "cohort" if alias == "cohort" else f"cohort_{alias}"
                for field in project_fields:
                    if not field or not isinstance(field, str):
                        raise ServiceError("Invalid cohort project field", status_code=400)
                    out_name = f"{prefix}_{field}"
                    expr_sql = f"{alias}.{self._safe_ident(field)} AS {self._safe_alias(out_name)}"
                    selects.append((expr_sql, out_name))
                    exprid_sql[f"cohort:{cohort_att_id}:cohort:{field}"] = f"{alias}.{self._safe_ident(field)}"

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
        using_prep: bool,
        base_alias: str,
        alias_by_wt: Dict[int, str],
    ) -> str:
        parts: List[str] = []
        for s in sorting:
            if not isinstance(s, dict):
                raise ServiceError("Invalid sorting entry", status_code=400)

            col = s.get("col") if "col" in s else s.get("columnName")
            col_expr = self._col_expr(
                col,
                derived_by_exprid,
                derived_by_name,
                rewrite_by_colname,
                rewrite_by_modelid,
                using_prep,
                base_alias,
                alias_by_wt,
            )

            dir_ = (s.get("dir") or "asc").lower()
            if dir_ not in ("asc", "desc"):
                raise ServiceError("Invalid sort direction", status_code=400)

            parts.append(f"{col_expr} {dir_.upper()}")
        return ", ".join(parts)

    # -----------------------------
    # Column/row inference & shaping
    # -----------------------------
    def _columns_from_query_json(self, q: dict) -> List[Dict[str, Any]]:
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

    def _infer_columns_from_rows(self, rows: List[Any]) -> List[Dict[str, Any]]:
        if not rows:
            return []
        first = rows[0]
        if isinstance(first, dict):
            return [{"key": k, "label": k} for k in first.keys()]
        return []

    def _extract_total(self, count_rows: List[Any]) -> int:
        if not count_rows:
            return 0
        first = count_rows[0]
        if isinstance(first, dict):
            return int(first.get("total") or 0)
        if isinstance(first, (list, tuple)) and len(first) >= 1:
            return int(first[0] or 0)
        return 0

    def _rows_to_dicts(self, rows_any, columns):
        if not rows_any:
            return []

        if isinstance(rows_any, list) and rows_any and isinstance(rows_any[0], dict):
            return rows_any

        if not columns:
            return []

        if isinstance(columns, list) and columns and isinstance(columns[0], dict):
            keys = [c.get("key") for c in columns]
        else:
            keys = list(columns)

        out = []
        for row in rows_any:
            if not isinstance(row, (list, tuple)):
                continue
            out.append({keys[i]: (row[i] if i < len(row) else None) for i in range(len(keys))})
        return out
