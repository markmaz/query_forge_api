from __future__ import annotations

import re
from typing import Any, Callable, Dict, List, Optional, Tuple

from app.exceptions.forge_error import ForgeError
from app.services.query_forge.value_override_constants import (
    VALUE_OVERRIDE_FIELDS_BY_TYPE,
    VALUE_OVERRIDE_JOIN_ALIAS_BY_TYPE,
    VALUE_OVERRIDE_KEY_BY_TYPE,
    VALUE_OVERRIDE_PROJECT_ALIASES_BY_TYPE,
)
from app.services.value_overrides.list_schema import TABLE_BY_TYPE


class QueryForgeAttachmentCompiler:
    _IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

    def __init__(
        self,
        *,
        normalize_col_key: Callable[[Any, str], Dict[str, Any]],
        col_expr: Callable[..., str],
        qf_safe_ident: Callable[[str], str],
        safe_alias: Callable[[str], str],
        safe_table_full_name: Callable[[str], str],
    ) -> None:
        self._normalize_col_key = normalize_col_key
        self._col_expr = col_expr
        self._qf_safe_ident = qf_safe_ident
        self._safe_alias = safe_alias
        self._safe_table_full_name = safe_table_full_name

    def compile(
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
        workspace_id: Optional[str],
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
