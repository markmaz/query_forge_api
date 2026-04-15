# app/services/query_forge/service.py
from __future__ import annotations

import re
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple, Union

from app.exceptions.forge_error import ForgeError
from app.ports.sql_executor import ForgeQueryPort
from app.services.domain_resolver import DomainPlan, DomainResolver
from app.services.query_forge.attachment_compiler import QueryForgeAttachmentCompiler
from app.services.query_forge.compile_context_builder import QueryForgeCompileContextBuilder
from app.services.query_forge.join_compiler import QueryForgeJoinCompiler
from app.services.query_forge.metric_compiler import QueryForgeMetricCompiler
from app.services.query_forge.normalizers import QueryForgeQueryNormalizer
from app.services.query_forge.order_by_compiler import QueryForgeOrderByCompiler
from app.services.query_forge.plan_inspector import QueryForgePlanInspector
from app.services.query_forge.projection_compiler import QueryForgeProjectionCompiler
from app.services.query_forge.requirements import QueryForgeRequirementAnalyzer
from app.services.query_forge.result_mapper import (
    cols_from_json as _rm_cols_from_json,
    extract_total as _rm_extract_total,
    infer_cols as _rm_infer_cols,
    rows_to_dicts as _rm_rows_to_dicts,
)
from app.services.query_forge.sql_assembler import QueryForgeSqlAssembler
from app.services.query_forge.split_ratio_query_coordinator import QueryForgeSplitRatioCoordinator
from app.services.query_forge.standard_compiler import QueryForgeStandardCompiler
from app.services.query_forge.sql_utils import (
    col_expr as _su_col_expr,
    dp_ident as _su_dp_ident,
    literal_sql as _su_literal_sql,
    physical_col_expr as _su_physical_col_expr,
    render_sql as _su_render_sql,
    safe_alias as _su_safe_alias,
    safe_ident as _su_safe_ident,
)
from app.services.query_forge.where_compiler import (
    QF_MAX_MANUAL_IN,
    WhereCompiler,
    build_and_filter_tree as _wc_build_and_filter_tree,
    flatten_and_conditions as _wc_flatten_and_conditions,
    is_and_only_filter_tree as _wc_is_and_only_filter_tree,
)
from app.services.query_forge.data_prep_compiler import DataPrepCompiler as _DataPrepCompiler
from app.services.query_forge.split_ratio_compiler import (
    detect_split_ratio_metric as _src_detect_split_ratio_metric,
)
from app.services.sqljson import validate_and_normalize_derived_sqljson
from app.services.value_overrides.list_schema import TABLE_BY_TYPE

GLOBAL_ROW_QUALITY_COLUMN = "tdoe_severity_code"
GLOBAL_ROW_QUALITY_MAX_EXCLUSIVE = 4

# Dataclasses moved to app.services.query_forge.types — re-exported here for
# backwards-compatibility with any code that imports them from this module.
from app.services.query_forge.types import (  # noqa: E402
    CompilationContext,
    ForgeCompiledQuery,
    QueryForgePreparedQuery,
    QueryForgeRunResult,
)


QfColumnKey = Union[str, Dict[str, Any]]  # legacy strings + new {workspaceTableId?,modelColumnId,columnName,exprId?}

__all__ = [
    "QF_MAX_MANUAL_IN",
    "TABLE_BY_TYPE",
    "QueryForgeService",
]


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
        self._normalizer = QueryForgeQueryNormalizer()
        self._plan_inspector = QueryForgePlanInspector(domain_resolver)
        self._requirements = QueryForgeRequirementAnalyzer(
            normalize_col_key=lambda *args, **kwargs: self._normalizer.normalize_col_key(*args, **kwargs),
            effective_filter_mode=lambda *args, **kwargs: self._effective_filter_mode(*args, **kwargs),
        )
        self._attachment_compiler = QueryForgeAttachmentCompiler(
            normalize_col_key=lambda *args, **kwargs: self._normalizer.normalize_col_key(*args, **kwargs),
            col_expr=lambda *args, **kwargs: self._col_expr(*args, **kwargs),
            qf_safe_ident=lambda *args, **kwargs: self._qf_safe_ident(*args, **kwargs),
            safe_alias=lambda *args, **kwargs: self._safe_alias(*args, **kwargs),
            safe_table_full_name=lambda *args, **kwargs: self._safe_table_full_name(*args, **kwargs),
        )
        self._compile_context_builder = QueryForgeCompileContextBuilder(
            required_table_ids_from_query=lambda *args, **kwargs: self._required_table_ids_from_query(*args, **kwargs),
            attach_table_ids=lambda *args, **kwargs: self._qf_attach_table_ids(*args, **kwargs),
            from_clause_from_plan=lambda *args, **kwargs: self._from_clause_from_plan(*args, **kwargs),
            compile_data_prep_meta=lambda *args, **kwargs: self._compile_data_prep_meta(*args, **kwargs),
            severity_predicate_for_alias=lambda *args, **kwargs: self._severity_predicate_for_alias(*args, **kwargs),
            collect_required_column_keys=lambda *args, **kwargs: self._collect_required_column_keys(*args, **kwargs),
            build_prep_base_selects=lambda *args, **kwargs: self._build_prep_base_selects(*args, **kwargs),
            render_data_prep_cte=lambda *args, **kwargs: self._render_data_prep_cte(*args, **kwargs),
            compile_attachments=lambda *args, **kwargs: self._compile_attachments(*args, **kwargs),
            qf_safe_ident=lambda *args, **kwargs: self._qf_safe_ident(*args, **kwargs),
        )
        self._order_by_compiler = QueryForgeOrderByCompiler(
            col_expr=lambda *args, **kwargs: self._col_expr(*args, **kwargs),
            safe_alias=lambda *args, **kwargs: self._safe_alias(*args, **kwargs),
        )
        self._metric_compiler = QueryForgeMetricCompiler(
            col_expr=lambda *args, **kwargs: self._col_expr(*args, **kwargs),
        )
        self._projection_compiler = QueryForgeProjectionCompiler(
            col_expr=lambda *args, **kwargs: self._col_expr(*args, **kwargs),
            compile_metric=lambda *args, **kwargs: self._compile_metric(*args, **kwargs),
            safe_alias=lambda *args, **kwargs: self._safe_alias(*args, **kwargs),
            col_label_key=lambda *args, **kwargs: self._col_label_key(*args, **kwargs),
        )
        self._join_compiler = QueryForgeJoinCompiler(
            qf_safe_ident=lambda *args, **kwargs: self._qf_safe_ident(*args, **kwargs),
        )
        self._sql_assembler = QueryForgeSqlAssembler(
            qf_safe_ident=lambda *args, **kwargs: self._qf_safe_ident(*args, **kwargs),
            from_clause_from_plan=lambda *args, **kwargs: self._from_clause_from_plan(*args, **kwargs),
        )
        self._split_ratio_coordinator = QueryForgeSplitRatioCoordinator(
            severity_predicate_for_alias=lambda *args, **kwargs: self._severity_predicate_for_alias(*args, **kwargs),
            qf_safe_ident=lambda *args, **kwargs: self._qf_safe_ident(*args, **kwargs),
            compile_where=lambda *args, **kwargs: self._compile_where(*args, **kwargs),
            from_clause_from_plan=lambda *args, **kwargs: self._from_clause_from_plan(*args, **kwargs),
            required_table_ids_from_query=lambda *args, **kwargs: self._required_table_ids_from_query(*args, **kwargs),
            compile_metric=lambda *args, **kwargs: self._compile_metric(*args, **kwargs),
        )
        self._standard_compiler = QueryForgeStandardCompiler(
            build_context=lambda *args, **kwargs: self._compile_context_builder.build(*args, **kwargs),
            filter_table_ids=lambda *args, **kwargs: self._qf_filter_table_ids(*args, **kwargs),
            sorting_table_ids=lambda *args, **kwargs: self._qf_sorting_table_ids(*args, **kwargs),
            compile_projection=lambda *args, **kwargs: self._projection_compiler.compile(*args, **kwargs),
            merge_attachment_selects=lambda *args, **kwargs: self._projection_compiler.merge_attachment_selects(*args, **kwargs),
            select_two_phase_key_column=lambda *args, **kwargs: self._select_two_phase_key_column(*args, **kwargs),
            compile_where=lambda *args, **kwargs: self._compile_where(*args, **kwargs),
            compile_order_by=lambda *args, **kwargs: self._compile_order_by(*args, **kwargs),
            assemble_sql=lambda *args, **kwargs: self._sql_assembler.assemble(*args, **kwargs),
        )
        self._where_compiler = WhereCompiler(
            get_join_path=lambda plan, target_id: self._domains.get_join_path(plan, target_id),
            join_predicates=lambda *args, **kwargs: self._qf_join_predicates(*args, **kwargs),
            severity_predicate_for_alias=lambda *args, **kwargs: self._severity_predicate_for_alias(*args, **kwargs),
            effective_filter_mode=lambda *args, **kwargs: self._effective_filter_mode(*args, **kwargs),
            max_manual_in=lambda: QF_MAX_MANUAL_IN,
        )

    def run(
        self,
        query_json: Dict[str, Any],
        *,
        mode: str = "preview",
        limit: int = 200,
        offset: int = 0,
    ) -> QueryForgeRunResult:
        normalized = self.normalize(query_json)
        compiled = self.compile(normalized, mode=mode, limit=limit, offset=offset)

        data = self._executor.submit_statement(compiled.sql, parameters=compiled.params)
        qf_result_rows = (data or {}).get("rows") or []

        count = self._executor.submit_statement(compiled.qf_count_sql, parameters=compiled.params)
        total = _rm_extract_total((count or {}).get("rows") or [])

        columns = (
            _rm_infer_cols(qf_result_rows)
            or compiled.qf_output_cols
            or _rm_cols_from_json(normalized)
        )
        rows = _rm_rows_to_dicts(qf_result_rows, columns)

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
        query_json: Dict[str, Any],
        *,
        mode: str = "preview",
        limit: int = 200,
        offset: int = 0,
    ) -> QueryForgePreparedQuery:
        normalized = self.normalize(query_json)
        compiled = self.compile(normalized, mode=mode, limit=limit, offset=offset)
        columns = compiled.qf_output_cols or _rm_cols_from_json(normalized)
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
    def normalize(self, q: Dict[str, Any]) -> Dict[str, Any]:
        return self._normalizer.normalize(q)

    def _qf_attach_table_ids(
        self,
        value_override_attachments: List[Any],
        cohort_attachment: Optional[Dict[str, Any]],
        primary_id: int,
    ) -> set[int]:
        return self._normalizer.attachment_table_ids(
            value_override_attachments=value_override_attachments,
            cohort_attachment=cohort_attachment,
            primary_id=primary_id,
        )

    # -----------------------------
    # Compile
    # -----------------------------
    _IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

    def _qf_supports_array_params(self) -> bool:
        if hasattr(self._executor, "supports_array_params"):
            return bool(getattr(self._executor, "supports_array_params"))
        return "databricks" in self._executor.__class__.__name__.lower()

    def _qf_filter_table_ids(self, node: Any, plan: DomainPlan) -> set[int]:
        return self._normalizer.filter_table_ids(node, plan)

    def _qf_sorting_table_ids(self, sorting: List[Dict[str, Any]], plan: DomainPlan) -> set[int]:
        return self._normalizer.sorting_table_ids(sorting, plan)

    def _select_two_phase_key_column(
        self,
        *,
        q: Dict[str, Any],
        plan: DomainPlan,
        primary_id: int,
        filter_only_table_ids: set[int],
    ) -> Optional[str]:
        return self._plan_inspector.select_two_phase_key_column(
            q=q,
            plan=plan,
            primary_id=primary_id,
            filter_only_table_ids=filter_only_table_ids,
        )

    def _primary_join_key_candidates(
        self,
        *,
        plan: DomainPlan,
        primary_id: int,
        filter_only_table_ids: set[int],
    ) -> List[str]:
        return self._plan_inspector.primary_join_key_candidates(
            plan=plan,
            primary_id=primary_id,
            filter_only_table_ids=filter_only_table_ids,
        )

    @staticmethod
    def _primary_query_key_candidates(*, q: Dict[str, Any], primary_id: int) -> List[str]:
        return QueryForgePlanInspector.primary_query_key_candidates(q=q, primary_id=primary_id)

    @staticmethod
    def _looks_like_identifier_column(column_name: str) -> bool:
        return QueryForgePlanInspector.looks_like_identifier_column(column_name)

    def _load_domain_column_catalog(self, plan: DomainPlan) -> Dict[tuple[int, str], Dict[str, Any]]:
        return self._plan_inspector.load_domain_column_catalog(plan)

    @staticmethod
    def _workspace_table_ids_with_column(
        plan: DomainPlan,
        *,
        column_name: str,
        column_catalog: Optional[Dict[tuple[int, str], Dict[str, Any]]] = None,
    ) -> set[int]:
        return QueryForgePlanInspector.workspace_table_ids_with_column(
            plan,
            column_name=column_name,
            column_catalog=column_catalog,
        )

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
        return _wc_is_and_only_filter_tree(node)

    @staticmethod
    def _flatten_and_conditions(node: Any) -> List[Dict[str, Any]]:
        return _wc_flatten_and_conditions(node)

    @staticmethod
    def _build_and_filter_tree(conditions: Sequence[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        return _wc_build_and_filter_tree(conditions)

    def compile(self, q: Dict[str, Any], mode: str = "preview", limit: int = 200, offset: int = 0) -> ForgeCompiledQuery:
        if mode not in ("preview", "export"):
            raise ForgeError("Invalid mode", status_code=400)

        filters = self._normalizer.normalize_filters(q.get("filters"))
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
            return self._split_ratio_coordinator.compile(
                q=q,
                plan=plan,
                split_metric=split_metric,
                mode=mode,
                limit=limit,
                offset=offset,
                severity_table_ids=severity_table_ids,
            )
        return self._standard_compiler.compile(
            q=q,
            plan=plan,
            mode=mode,
            limit=limit,
            offset=offset,
            severity_table_ids=severity_table_ids,
        )

    def _detect_split_ratio_metric(self, q: Dict[str, Any], plan: DomainPlan) -> Optional[Dict[str, Any]]:
        return _src_detect_split_ratio_metric(q, primary_id=int(plan.primary.workspace_table_id))

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
        return _DataPrepCompiler()._compile_meta(data_prep, qf_base_alias=qf_base_alias, alias_by_wt=alias_by_wt)
    def _render_data_prep_cte(
        self,
        *,
        base_from_sql: str,
        base_selects: List[str],
        exprs: List[str],
        base_where_sql: str = "",
    ) -> str:
        return _DataPrepCompiler()._render_cte(
            base_from_sql=base_from_sql,
            base_selects=base_selects,
            exprs=exprs,
            base_where_sql=base_where_sql,
        )
    def _from_clause_from_plan(
        self,
        plan: DomainPlan,
        required_table_ids: set[int],
        *,
        severity_table_ids: Optional[set[int]] = None,
    ) -> str:
        return self._join_compiler.compile_from_plan(
            plan,
            required_table_ids,
            get_join_path=lambda active_plan, wt_id: self._domains.get_join_path(active_plan, wt_id),
            severity_predicate_for_alias=lambda *args, **kwargs: self._severity_predicate_for_alias(*args, **kwargs),
            severity_table_ids=severity_table_ids,
        )

    def _qf_compile_join_on(self, edge: Any, alias_by_wt: Dict[int, str]) -> str:
        return self._join_compiler.compile_join_on(edge, alias_by_wt)

    def _qf_join_predicates(self, edge: Any, from_alias: str, to_alias: str) -> List[str]:
        return self._join_compiler.join_predicates(edge, from_alias, to_alias)

    def _compile_join_side(self, side: Dict[str, Any], *, expected_scope: str, alias: str) -> str:
        return self._join_compiler.compile_join_side(side, expected_scope=expected_scope, alias=alias)

    def _parse_join_expr(self, expr: str) -> tuple[str, str, str]:
        return self._join_compiler.parse_join_expr(expr)

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
        return self._requirements.required_table_ids_from_query(q, plan)

    def _collect_required_column_keys(
        self,
        q: Dict[str, Any],
        plan: DomainPlan,
        *,
        required_table_ids: set[int],
        derived_by_exprid: Dict[str, str],
        derived_by_name: Dict[str, str],
    ) -> List[Dict[str, Any]]:
        return self._requirements.collect_required_column_keys(
            q,
            plan,
            required_table_ids=required_table_ids,
            derived_by_exprid=derived_by_exprid,
            derived_by_name=derived_by_name,
        )

    def _build_prep_base_selects(
        self,
        required_cols: List[Dict[str, Any]],
        *,
        primary_id: int,
        qf_base_alias: str,
        alias_by_wt: Dict[int, str],
    ) -> Tuple[List[str], Dict[str, str], Dict[int, str], Dict[tuple, str]]:
        return _DataPrepCompiler().build_prep_base_selects(
            required_cols,
            primary_id=primary_id,
            qf_base_alias=qf_base_alias,
            alias_by_wt=alias_by_wt,
        )
    def _qf_render_sql(self, sql: str, params: Dict[str, Any]) -> str:
        return _su_render_sql(sql, params)

    def _literal_sql(self, v: Any) -> str:
        return _su_literal_sql(v)

    # -----------------------------
    # Helpers (safe identifiers — delegated to sql_utils)
    # -----------------------------
    def _qf_safe_ident(self, s: str) -> str:
        return _su_safe_ident(s)

    def _safe_table_full_name(self, name: str) -> str:
        if not name or not isinstance(name, str):
            raise ForgeError("Invalid table name", status_code=400)
        parts = [p.strip() for p in name.split(".") if p.strip()]
        if not parts:
            raise ForgeError("Invalid table name", status_code=400)
        return ".".join(f"`{self._qf_safe_ident(p)}`" for p in parts)

    def _safe_alias(self, s: str) -> str:
        return _su_safe_alias(s)

    def _dp_ident(self, qf_out_name: str) -> str:
        return _su_dp_ident(qf_out_name)

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
        return _su_col_expr(
            key_or_ref,
            derived_by_exprid,
            derived_by_name,
            rewrite_by_colname,
            rewrite_by_modelid,
            qf_using_prep,
            qf_base_alias,
            alias_by_wt,
            rewrite_by_wt_col=rewrite_by_wt_col,
        )

    def _physical_col_expr(self, col_name: str, qf_using_prep: bool, qf_base_alias: str, alias: str | None) -> str:
        return _su_physical_col_expr(col_name, qf_using_prep=qf_using_prep, qf_base_alias=qf_base_alias, alias=alias)

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
        return self._metric_compiler.compile(
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
        context = CompilationContext(
            derived_by_exprid=derived_by_exprid,
            derived_by_name=derived_by_name,
            rewrite_by_colname=rewrite_by_colname,
            rewrite_by_modelid=rewrite_by_modelid,
            rewrite_by_wt_col=rewrite_by_wt_col,
        )
        return self._where_compiler.compile(
            node=node,
            context=context,
            qf_using_prep=qf_using_prep,
            qf_base_alias=qf_base_alias,
            alias_by_wt=alias_by_wt,
            plan=plan,
            new_param=new_param,
            filter_mode_fn=lambda active_plan, workspace_table_id: self._effective_filter_mode(active_plan, workspace_table_id),
            force_exists_for_tables=force_exists_for_tables,
            severity_table_ids=severity_table_ids,
        )

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
        del plan
        return self._attachment_compiler.compile(
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
            workspace_id=getattr(self._domains, "_workspace_id", None),
            new_param=new_param,
        )

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
        return self._order_by_compiler.compile(
            sorting,
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
