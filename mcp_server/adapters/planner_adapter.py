from __future__ import annotations

from typing import Any, Dict, Mapping

from app.features.planner.service import PlannerFeatureService
from app.models.query.ai_suggest import (
    AddAggregateEdit,
    AddFilterEdit,
    AddGroupByEdit,
    AddSelectEdit,
    AddSortEdit,
    SetDomainEdit,
)
from app.services.domain_resolver import DomainResolver
from app.services.domains.capabilities_service import DomainCapabilitiesService
from app.services.query_forge.service import QueryForgeService
from app.services.sqljson_apply_service import apply_edits
from app.services.workspace_inventory.workspace_context import WorkspaceSqlContextBuilder

from ..config import MCPSettings
from ..context import RequestContext
from ..exceptions import MCPError
from ..schemas.common import ColumnSchema, ExecutionMetadata
from ..schemas.planner import (
    CompileQueryResponse,
    PlanField,
    PlanFilter,
    PlanQueryResponse,
    PlanSort,
    PreviewQueryResponse,
    QueryPlan,
    ValidateQueryPlanResponse,
)
from .domain_adapter import DomainAdapter
from .helpers import flatten_filter_groups, normalize_text, sql_column_key_from_row


class PlannerAdapter:
    def __init__(
        self,
        *,
        settings: MCPSettings,
        planner_feature_service: PlannerFeatureService | None = None,
        capabilities_service: DomainCapabilitiesService | None = None,
        domain_adapter: DomainAdapter | None = None,
        context_builder: WorkspaceSqlContextBuilder | None = None,
    ) -> None:
        self._settings = settings
        self._planner = planner_feature_service or PlannerFeatureService()
        self._capabilities = capabilities_service or DomainCapabilitiesService()
        self._domains = domain_adapter or DomainAdapter(capabilities_service=self._capabilities)
        self._context_builder = context_builder or WorkspaceSqlContextBuilder()

    def plan_query(
        self,
        *,
        request_context: RequestContext,
        prompt: str,
        domain_key: str,
        context: Mapping[str, Any],
    ) -> PlanQueryResponse:
        domain = self._domains.resolve_domain(request_context=request_context, domain_key=domain_key)
        result = self._planner.plan_domain(
            {
                "workspace_id": request_context.workspace_id,
                "prompt": prompt,
                "base_domain_id": int(domain["id"]),
                "fast_mode": True,
            },
            user_id=request_context.user_id,
        )
        sql_json = dict(result.get("sql_json") or {})
        plan_json_v2 = dict(result.get("plan_json_v2") or {})
        plan = self._plan_from_sql_json(
            domain_key=str(domain.get("key") or domain_key),
            sql_json=sql_json,
            plan_json_v2=plan_json_v2,
        )
        plan.explanations.append(
            f"Planned against QueryForge domain '{plan.domain_key}' using the governed planner."
        )
        if bool(result.get("needs_clarification")):
            question = normalize_text(result.get("clarification_question"))
            if question:
                plan.ambiguities.append(question)
                plan.warnings.append("Planner reported ambiguity and included a clarification question.")
        plan.internal.update(
            {
                "base_domain_id": int(domain["id"]),
                "plan_json_v2": plan_json_v2,
                "sql_json": sql_json,
                "planner_context": dict(context or {}),
            }
        )
        return PlanQueryResponse(**plan.model_dump(mode="json"))

    def validate_query_plan(
        self,
        *,
        request_context: RequestContext,
        plan: QueryPlan,
    ) -> ValidateQueryPlanResponse:
        normalized = QueryPlan.model_validate(plan.model_dump(mode="json"))
        domain = self._domains.resolve_domain(request_context=request_context, domain_key=normalized.domain_key)
        capabilities = self._capabilities.get_domain_capabilities(
            workspace_id=request_context.workspace_id,
            user_id=request_context.user_id,
            domain_id=int(domain["id"]),
        )
        dimension_rows = list(capabilities.get("dimensions") or [])
        metric_rows = list(capabilities.get("domain_metrics") or [])
        dimension_map = {
            str(item.get("column_key") or "").strip().lower(): dict(item)
            for item in dimension_rows
            if str(item.get("column_key") or "").strip()
        }
        metric_map = {
            str(item.get("metric_key") or "").strip().lower(): dict(item)
            for item in metric_rows
            if str(item.get("metric_key") or "").strip()
        }
        errors: list[dict[str, Any]] = []
        warnings: list[str] = list(normalized.warnings)

        normalized_fields: list[PlanField] = []
        for index, field in enumerate(normalized.selected_fields):
            key = normalize_text(field.key).lower()
            if field.role == "dimension":
                row = dimension_map.get(key)
                if row is None:
                    errors.append({"path": f"selected_fields[{index}]", "message": f"Unknown dimension '{field.key}'"})
                    continue
                normalized_fields.append(
                    PlanField(
                        key=str(row.get("column_key") or field.key),
                        role="dimension",
                        label=str(row.get("label") or field.label or field.key),
                    )
                )
            else:
                row = metric_map.get(key)
                if row is None:
                    errors.append({"path": f"selected_fields[{index}]", "message": f"Unknown metric '{field.key}'"})
                    continue
                normalized_fields.append(
                    PlanField(
                        key=str(row.get("metric_key") or field.key),
                        role="metric",
                        label=str(row.get("label") or field.label or field.key),
                    )
                )

        normalized_filters: list[PlanFilter] = []
        allowed_filter_keys = set(dimension_map)
        for index, item in enumerate(normalized.filters):
            key = normalize_text(item.key).lower()
            if key not in allowed_filter_keys:
                errors.append({"path": f"filters[{index}]", "message": f"Unknown filter field '{item.key}'"})
                continue
            operator = normalize_text(item.operator).lower()
            if operator not in {"equals", "not_equals", "contains", "starts_with", "in", "not_in", "gt", "gte", "lt", "lte", "between", "is_null", "is_not_null"}:
                errors.append({"path": f"filters[{index}]", "message": f"Unsupported operator '{item.operator}'"})
                continue
            normalized_filters.append(
                PlanFilter(
                    key=str(dimension_map[key].get("column_key") or item.key),
                    operator=operator,
                    value=item.value,
                )
            )

        normalized_sort: list[PlanSort] = []
        allowed_sort_keys = {
            normalize_text(field.key).lower()
            for field in normalized_fields
            if field.role == "dimension"
        } | set(allowed_filter_keys)
        for index, item in enumerate(normalized.sort):
            key = normalize_text(item.key).lower()
            if key not in allowed_sort_keys:
                errors.append({"path": f"sort[{index}]", "message": f"Unknown sort field '{item.key}'"})
                continue
            normalized_sort.append(
                PlanSort(
                    key=str(dimension_map.get(key, {}).get("column_key") or item.key),
                    direction=item.direction,
                )
            )

        has_metric = any(field.role == "metric" for field in normalized_fields)
        if normalized.intent == "aggregate" and not has_metric:
            errors.append({"path": "intent", "message": "Aggregate plans require at least one metric."})
        if normalized.intent == "trend" and not normalized_sort:
            warnings.append("Trend plans typically sort by a time-compatible dimension.")
        if not request_context.can_preview:
            errors.append({"path": "workspace_id", "message": "Preview execution is disabled for this caller."})

        normalized_plan = QueryPlan(
            plan_version=normalized.plan_version,
            status="ok" if not errors else "invalid",
            intent=normalized.intent,
            domain_key=str(domain.get("key") or normalized.domain_key),
            selected_fields=normalized_fields,
            filters=normalized_filters,
            sort=normalized_sort,
            explanations=list(normalized.explanations),
            ambiguities=list(normalized.ambiguities),
            warnings=warnings,
            internal={
                "base_domain_id": int(domain["id"]),
            },
        )
        return ValidateQueryPlanResponse(
            valid=not errors,
            errors=errors,
            warnings=warnings,
            normalized_plan=normalized_plan,
        )

    def compile_query(
        self,
        *,
        request_context: RequestContext,
        plan: QueryPlan,
    ) -> CompileQueryResponse:
        validation = self.validate_query_plan(request_context=request_context, plan=plan)
        if not validation.valid:
            raise MCPError(
                error_code="VALIDATION_FAILED",
                message="Query plan failed validation",
                details={"errors": validation.errors},
                status_code=422,
            )
        sql_json = self._compile_sql_json(
            request_context=request_context,
            plan=validation.normalized_plan,
        )
        prepared = self._prepare_query(
            workspace_id=request_context.workspace_id,
            sql_json=sql_json,
            limit=self._settings.preview_default_limit,
        )
        sql_value = prepared.qf_rendered_sql if self._settings.include_raw_sql else None
        return CompileQueryResponse(
            sql_json=sql_json,
            compiled={
                "dialect": "databricks",
                "sql": sql_value,
                "parameterized": True,
            },
            execution_metadata=ExecutionMetadata(
                row_limit=self._settings.preview_default_limit,
                timeout_seconds=self._settings.preview_timeout_seconds,
            ),
        )

    def preview_query(
        self,
        *,
        request_context: RequestContext,
        plan: QueryPlan,
        limit: int,
    ) -> PreviewQueryResponse:
        if not request_context.can_preview:
            raise MCPError(
                error_code="EXECUTION_DISABLED",
                message="Preview execution is not enabled for this caller",
                status_code=403,
            )
        requested_limit = int(limit or self._settings.preview_default_limit)
        if requested_limit > self._settings.preview_hard_limit:
            raise MCPError(
                error_code="PREVIEW_LIMIT_EXCEEDED",
                message=f"Preview limit exceeds hard max of {self._settings.preview_hard_limit}",
                status_code=400,
            )
        effective_limit = min(requested_limit, self._settings.preview_default_limit)
        validation = self.validate_query_plan(request_context=request_context, plan=plan)
        if not validation.valid:
            raise MCPError(
                error_code="VALIDATION_FAILED",
                message="Query plan failed validation",
                details={"errors": validation.errors},
                status_code=422,
            )
        sql_json = self._compile_sql_json(
            request_context=request_context,
            plan=validation.normalized_plan,
        )
        ctx = self._context_builder.build(request_context.workspace_id)
        qf = QueryForgeService(
            executor=ctx.sql_exec,
            domain_resolver=DomainResolver(workspace_id=request_context.workspace_id),
        )
        result = qf.run(sql_json, mode="preview", limit=effective_limit, offset=0)
        return PreviewQueryResponse(
            columns=[
                ColumnSchema(
                    name=str(col.get("name") or col.get("key") or ""),
                    type=str(col.get("type") or col.get("dataType") or col.get("data_type") or ""),
                    label=str(col.get("label") or col.get("name") or col.get("key") or ""),
                )
                for col in list(result.columns or [])
            ],
            rows=[dict(row) for row in list(result.rows or [])],
            truncated=bool((result.total or 0) > len(result.rows or [])),
            row_count_returned=len(result.rows or []),
        )

    def _plan_from_sql_json(
        self,
        *,
        domain_key: str,
        sql_json: Mapping[str, Any],
        plan_json_v2: Mapping[str, Any],
    ) -> QueryPlan:
        selected_fields: list[PlanField] = []
        columns = list(sql_json.get("columns") or [])
        for item in columns:
            field = dict(item.get("field") or {})
            key = f"wt{field.get('workspaceTableId')}.{str(field.get('columnName') or '').strip().lower()}"
            if str(field.get("columnName") or "").strip():
                selected_fields.append(
                    PlanField(
                        key=key,
                        role="dimension",
                        label=str(item.get("alias") or field.get("columnName") or key),
                    )
                )

        aggs = dict(sql_json.get("aggs") or {})
        for item in list(aggs.get("metrics") or []):
            field = dict(item.get("field") or {})
            if field:
                key = f"wt{field.get('workspaceTableId')}.{str(field.get('columnName') or '').strip().lower()}"
            else:
                key = str(item.get("label") or item.get("fn") or "count")
            selected_fields.append(
                PlanField(
                    key=key,
                    role="metric",
                    label=str(item.get("label") or key),
                )
            )
        filters = [
            PlanFilter(
                key=f"wt{(field := dict(item.get('field') or {})).get('workspaceTableId')}.{str(field.get('columnName') or '').strip().lower()}",
                operator=str(item.get("op") or "equals"),
                value=item.get("value"),
            )
            for item in flatten_filter_groups(sql_json.get("filters"))
            if str((dict(item.get("field") or {})).get("columnName") or "").strip()
        ]
        sort = [
            PlanSort(
                key=f"wt{(field := dict(item.get('col') or {})).get('workspaceTableId')}.{str(field.get('columnName') or '').strip().lower()}",
                direction=str(item.get("dir") or "asc"),
            )
            for item in list(sql_json.get("sorting") or [])
            if str((dict(item.get("col") or {})).get("columnName") or "").strip()
        ]
        intent = str(plan_json_v2.get("intent") or "").strip().lower()
        if intent == "list":
            intent = "listing"
        if intent not in {"listing", "aggregate", "trend"}:
            intent = "aggregate" if aggs.get("enabled") else "listing"
        return QueryPlan(
            intent=intent,
            domain_key=domain_key,
            selected_fields=selected_fields,
            filters=filters,
            sort=sort,
            explanations=[],
            ambiguities=[],
            warnings=[],
            internal={},
        )

    def _compile_sql_json(
        self,
        *,
        request_context: RequestContext,
        plan: QueryPlan,
    ) -> dict[str, Any]:
        seeded = dict(plan.internal.get("sql_json") or {}) if isinstance(plan.internal.get("sql_json"), Mapping) else {}
        if seeded:
            return seeded

        domain = self._domains.resolve_domain(request_context=request_context, domain_key=plan.domain_key)
        capabilities = self._capabilities.get_domain_capabilities(
            workspace_id=request_context.workspace_id,
            user_id=request_context.user_id,
            domain_id=int(domain["id"]),
        )
        dimension_rows = {
            str(item.get("column_key") or "").strip().lower(): dict(item)
            for item in list(capabilities.get("dimensions") or [])
        }
        metric_rows = {
            str(item.get("metric_key") or "").strip().lower(): dict(item)
            for item in list(capabilities.get("domain_metrics") or [])
        }

        edits: list[Any] = [SetDomainEdit(op="setDomain", domainId=int(domain["id"]))]
        for field in plan.selected_fields:
            if field.role == "dimension":
                row = dimension_rows.get(normalize_text(field.key).lower())
                col = sql_column_key_from_row(row or {})
                if col is None:
                    continue
                edits.append(AddSelectEdit(op="addSelect", col=col, alias=field.label))
                if plan.intent in {"aggregate", "trend"}:
                    edits.append(AddGroupByEdit(op="addGroupBy", col=col))
                continue
            metric = metric_rows.get(normalize_text(field.key).lower())
            if metric is None:
                continue
            metric_label = str(metric.get("label") or field.label or field.key)
            metric_column = None
            if metric.get("column_key"):
                metric_column = sql_column_key_from_row(
                    dimension_rows.get(str(metric.get("column_key") or "").strip().lower(), {})
                )
            func = str(metric.get("agg") or "count").strip().lower()
            if func not in {"count", "count_distinct", "sum", "avg"}:
                func = "count"
            edits.append(AddAggregateEdit(op="addAggregate", func=func, col=metric_column, alias=metric_label))

        for item in plan.filters:
            row = dimension_rows.get(normalize_text(item.key).lower())
            col = sql_column_key_from_row(row or {})
            if col is None:
                continue
            edits.append(AddFilterEdit(op="addFilter", col=col, operator=item.operator, value=item.value))

        for item in plan.sort:
            row = dimension_rows.get(normalize_text(item.key).lower())
            col = sql_column_key_from_row(row or {})
            if col is None:
                continue
            edits.append(AddSortEdit(op="addSort", col=col, dir=item.direction))

        sql_json = apply_edits(None, edits, prompt=f"MCP: {plan.domain_key}")
        sql_json.setdefault("meta", {})
        if isinstance(sql_json["meta"], dict):
            sql_json["meta"]["tool"] = "queryforge_mcp"
        return sql_json

    def _prepare_query(self, *, workspace_id: str, sql_json: Dict[str, Any], limit: int):
        ctx = self._context_builder.build(workspace_id)
        qf = QueryForgeService(
            executor=ctx.sql_exec,
            domain_resolver=DomainResolver(workspace_id=workspace_id),
        )
        return qf.prepare(sql_json, mode="preview", limit=limit, offset=0)
