from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.exceptions.forge_error import ForgeError
from app.models.query.ai_suggest import AddSelectEdit, SetDomainEdit, SqlColumnKey
from app.services.domain.planner_semantic_join_policy_service import PlannerSemanticJoinPolicyService
from app.services.sqljson_apply_service import apply_edits
from app.services.semantic.plan.models import LLMPlanPayload, SlotDrivenIntent
from app.services.semantic.plan.utils import (
    _candidate_by_concept,
    _candidate_by_mid,
    _to_float,
    _to_int,
)


class SqlJsonBuilder:
    def __init__(
        self,
        *,
        semantic_join_policy_service: Optional[PlannerSemanticJoinPolicyService] = None,
    ) -> None:
        self._semantic_join_policy_service = semantic_join_policy_service or PlannerSemanticJoinPolicyService()

    def build_plan_skeleton(
        self,
        *,
        prompt: str,
        domain_id: Optional[int],
        slot_intent: SlotDrivenIntent,
        role_guardrails: Dict[str, Any],
        candidate_columns: Sequence[Dict[str, Any]],
    ) -> Dict[str, Any]:
        dimensions = [dict(row) for row in list(role_guardrails.get("dimension_columns") or []) if isinstance(row, dict)]
        subgroups = [dict(row) for row in list(role_guardrails.get("subgroup_columns") or []) if isinstance(row, dict)]
        metrics = [dict(row) for row in list(role_guardrails.get("metric_columns") or []) if isinstance(row, dict)]
        time_columns = [dict(row) for row in list(role_guardrails.get("time_columns") or []) if isinstance(row, dict)]

        selected_columns: List[Dict[str, Any]] = []
        filters: List[Dict[str, Any]] = []
        notes: List[str] = []
        seen_mid: set[int] = set()
        for row in dimensions:
            mid = _to_int(row.get("model_column_id"))
            concept_key = str(row.get("concept_key") or "").strip().upper()
            if mid is None or concept_key == "" or mid in seen_mid:
                continue
            seen_mid.add(mid)
            selected_columns.append({"concept_key": concept_key, "model_column_id": mid})
        for row in subgroups[:1]:
            concept_key = str(row.get("concept_key") or "").strip().upper()
            if concept_key:
                if concept_key in {"RACE", "ETHNICITY", "RACE_ETHNICITY"}:
                    continue
                column_name = str(row.get("column_name") or "").strip().lower()
                subgroup_value: Any = True if concept_key.startswith("IS_") or column_name.startswith("is_") else "EL"
                filters.append({"concept_key": concept_key, "op": "=", "value": subgroup_value})

        if time_columns and slot_intent.normalized_time:
            time_row = time_columns[0]
            concept_key = str(time_row.get("concept_key") or "").strip().upper()
            time_value = slot_intent.normalized_time[0].key
            if concept_key and time_value:
                filters.append({"concept_key": concept_key, "op": "=", "value": time_value})

        if slot_intent.implies_count_metric(prompt):
            metric_row = metrics[0] if metrics else (candidate_columns[0] if candidate_columns else None)
            if isinstance(metric_row, dict):
                metric_key = str(metric_row.get("concept_key") or "").strip().upper()
                metric_mid = _to_int(metric_row.get("model_column_id"))
                if metric_mid is not None and metric_key and metric_mid not in seen_mid:
                    seen_mid.add(metric_mid)
                    selected_columns.append({"concept_key": metric_key, "model_column_id": metric_mid})
                    notes.append("skeleton_enforced_count")

        sql_json, _ = SqlJsonBuilder.build_grounded_sql_json(
            prompt=prompt,
            domain_id=domain_id,
            selected_columns=selected_columns,
            filters=filters,
            candidate_by_mid=_candidate_by_mid(candidate_columns),
            candidate_by_concept=_candidate_by_concept(candidate_columns),
            llm_sql_json={},
            policy_service=self._semantic_join_policy_service,
        )
        if slot_intent.implies_count_metric(prompt):
            sql_json = SqlJsonBuilder.inject_count_aggregation(
                sql_json=sql_json,
                metric_columns=list(role_guardrails.get("metric_columns") or []),
                dimension_columns=dimensions,
            )

        return {
            "sql_json": sql_json,
            "selected_columns": selected_columns,
            "filters": filters,
            "notes": notes,
        }

    def validate(self, *, sql_json: Any, allowed_model_column_ids: set[int]) -> None:
        if not allowed_model_column_ids:
            return
        if not isinstance(sql_json, dict):
            return
        illegal = SqlJsonBuilder.collect_illegal_model_column_ids(sql_json=sql_json, allowed_model_column_ids=allowed_model_column_ids)
        if illegal:
            raise ForgeError(
                "Planner used disallowed columns",
                status_code=502,
                details={"illegal_model_column_ids": sorted(illegal)},
            )

    def fallback_skeleton_plan(
        self,
        *,
        prompt: str,
        domain_id: Optional[int],
        skeleton: Dict[str, Any],
        candidate_columns: Sequence[Dict[str, Any]],
    ) -> Dict[str, Any]:
        selected_columns = [dict(item) for item in list(skeleton.get("selected_columns") or []) if isinstance(item, dict)]
        filters = [dict(item) for item in list(skeleton.get("filters") or []) if isinstance(item, dict)]
        sql_json, _ = SqlJsonBuilder.build_grounded_sql_json(
            prompt=prompt,
            domain_id=domain_id,
            selected_columns=selected_columns,
            filters=filters,
            candidate_by_mid=_candidate_by_mid(candidate_columns),
            candidate_by_concept=_candidate_by_concept(candidate_columns),
            llm_sql_json=dict((skeleton or {}).get("sql_json") or {}),
            policy_service=self._semantic_join_policy_service,
        )
        if isinstance((skeleton or {}).get("sql_json"), dict) and isinstance(((skeleton or {}).get("sql_json") or {}).get("aggs"), dict):
            sql_json["aggs"] = ((skeleton or {}).get("sql_json") or {}).get("aggs")
        return {
            "sql_json": sql_json,
            "selected_columns": selected_columns,
            "filters": filters,
            "join_plan": {},
            "confidence": 0.45,
            "notes": list((skeleton or {}).get("notes") or []),
        }

    @staticmethod
    def build_grounded_sql_json(
        *,
        prompt: str,
        domain_id: Optional[int],
        selected_columns: Sequence[Dict[str, Any]],
        filters: Sequence[Dict[str, Any]],
        candidate_by_mid: Dict[int, Dict[str, Any]],
        candidate_by_concept: Dict[str, List[Dict[str, Any]]],
        llm_sql_json: Dict[str, Any],
        policy_service: Optional[PlannerSemanticJoinPolicyService] = None,
    ) -> Tuple[Dict[str, Any], int]:
        dropped = 0
        edits: List[Any] = []
        filter_conditions: List[Dict[str, Any]] = []
        if domain_id is not None:
            try:
                edits.append(SetDomainEdit(op="setDomain", domainId=int(domain_id)))
            except (TypeError, ValueError):
                dropped += 1

        table_hint = SqlJsonBuilder.extract_from_table_hint(llm_sql_json)
        selected_rows_by_concept: Dict[str, List[Dict[str, Any]]] = {}

        for item in selected_columns:
            mid = _to_int(item.get("model_column_id"))
            if mid is None:
                dropped += 1
                continue
            row = candidate_by_mid.get(mid)
            if not isinstance(row, dict):
                dropped += 1
                continue
            concept_key = str(item.get("concept_key") or row.get("concept_key") or "").strip().upper()
            if concept_key:
                selected_rows_by_concept.setdefault(concept_key, []).append(row)
            column_name = str(row.get("column_name") or "").strip()
            if column_name == "":
                dropped += 1
                continue
            try:
                edits.append(
                    AddSelectEdit(
                        op="addSelect",
                        col=SqlColumnKey(
                            modelColumnId=mid,
                            columnName=column_name,
                            workspaceTableId=_to_int(row.get("workspace_table_id")),
                            exprId=None,
                            alias=None,
                        ),
                        alias=None,
                    )
                )
            except (TypeError, ValueError):
                dropped += 1

        for item in filters:
            concept_key = str(item.get("concept_key") or "").strip().upper()
            op = SqlJsonBuilder.normalize_filter_operator(str(item.get("op") or ""))
            if concept_key == "" or op is None:
                dropped += 1
                continue

            row = SqlJsonBuilder.resolve_filter_column(
                concept_key=concept_key,
                selected_rows_by_concept=selected_rows_by_concept,
                candidate_by_concept=candidate_by_concept,
                table_hint=table_hint,
                policy_service=policy_service,
            )
            if not isinstance(row, dict):
                dropped += 1
                continue
            mid = _to_int(row.get("model_column_id"))
            column_name = str(row.get("column_name") or "").strip()
            if mid is None or column_name == "":
                dropped += 1
                continue
            filter_conditions.append(
                {
                    "type": "condition",
                    "id": f"semantic_plan_filter_{len(filter_conditions) + 1}",
                    "field": {
                        "modelColumnId": mid,
                        "columnName": column_name,
                        "workspaceTableId": _to_int(row.get("workspace_table_id")),
                        "exprId": None,
                        "alias": None,
                    },
                    "op": op,
                    "value": item.get("value"),
                }
            )

        sql_json = apply_edits(None, edits, prompt=prompt)
        if filter_conditions:
            sql_json["filters"] = {
                "type": "group",
                "id": "semantic_plan_filters",
                "match": "and",
                "children": filter_conditions,
            }
        meta = sql_json.get("meta")
        if isinstance(meta, dict):
            meta["tool"] = "semantic_plan"
            if table_hint:
                meta["fromTableHint"] = table_hint
        return sql_json, dropped

    @staticmethod
    def ground_plan(
        plan: LLMPlanPayload,
        candidate_columns: Sequence[Dict[str, Any]],
        concepts: Sequence[Dict[str, Any]],
        *,
        prompt: str,
        domain_id: Optional[int],
    ) -> Dict[str, Any]:
        valid_mids = {int(col.get("model_column_id")) for col in candidate_columns if col.get("model_column_id") is not None}
        candidate_by_mid: Dict[int, Dict[str, Any]] = {}
        candidate_by_concept: Dict[str, List[Dict[str, Any]]] = {}
        for row in candidate_columns:
            mid = _to_int(row.get("model_column_id"))
            if mid is None:
                continue
            candidate_by_mid[mid] = dict(row)
            concept_key = str(row.get("concept_key") or "").strip().upper()
            if concept_key:
                candidate_by_concept.setdefault(concept_key, []).append(dict(row))
        mapped_concepts = set(candidate_by_concept.keys())

        selected_seen: set[int] = set()
        selected_columns: List[Dict[str, Any]] = []
        for item in plan.selected_columns:
            mid = int(item.model_column_id)
            if mid not in valid_mids or mid in selected_seen:
                continue
            selected_seen.add(mid)
            concept_key = str((candidate_by_mid.get(mid) or {}).get("concept_key") or item.concept_key).upper()
            selected_columns.append(
                {
                    "concept_key": concept_key,
                    "model_column_id": mid,
                }
            )
        filters = [
            item.model_dump(mode="json")
            for item in plan.filters
            if str(item.concept_key or "").upper() in mapped_concepts
        ]

        grounded_sql_json, sql_json_dropped = SqlJsonBuilder.build_grounded_sql_json(
            prompt=prompt,
            domain_id=domain_id,
            selected_columns=selected_columns,
            filters=filters,
            candidate_by_mid=candidate_by_mid,
            candidate_by_concept=candidate_by_concept,
            llm_sql_json=plan.sql_json,
        )

        removed = (len(plan.selected_columns) - len(selected_columns)) + (len(plan.filters) - len(filters)) + sql_json_dropped
        confidence = float(plan.confidence)
        notes = list(plan.notes)
        if removed > 0:
            confidence = max(0.0, confidence - min(0.2, removed * 0.03))
            notes.append(f"grounding_removed={removed}")

        return {
            "sql_json": grounded_sql_json,
            "selected_columns": selected_columns,
            "filters": filters,
            "join_plan": plan.join_plan,
            "confidence": round(confidence, 4),
            "notes": notes,
        }

    @staticmethod
    def normalize_llm_payload(
        payload: Dict[str, Any],
        *,
        candidate_columns: Sequence[Dict[str, Any]],
    ) -> Dict[str, Any]:
        if not isinstance(payload, dict):
            return {}

        normalized: Dict[str, Any] = dict(payload)
        normalized.setdefault("sql_json", {})

        concept_by_model_column_id: Dict[int, str] = {}
        concept_by_table_column: Dict[Tuple[str, str], str] = {}
        concept_by_column_name: Dict[str, Optional[str]] = {}
        for row in candidate_columns:
            mid = _to_int(row.get("model_column_id"))
            concept_key = str(row.get("concept_key") or "").strip().upper()
            table_name = str(row.get("table_name") or "").strip().lower()
            column_name = str(row.get("column_name") or "").strip().lower()
            if mid is not None and concept_key:
                concept_by_model_column_id[mid] = concept_key
            if table_name and column_name and concept_key:
                concept_by_table_column[(table_name, column_name)] = concept_key
            if column_name and concept_key:
                if column_name in concept_by_column_name and concept_by_column_name[column_name] != concept_key:
                    concept_by_column_name[column_name] = None
                elif column_name not in concept_by_column_name:
                    concept_by_column_name[column_name] = concept_key

        selected_columns: List[Dict[str, Any]] = []
        raw_selected = normalized.get("selected_columns")
        if isinstance(raw_selected, list):
            for item in raw_selected:
                if isinstance(item, (int, float, str)):
                    mid = _to_int(item)
                    if mid is None:
                        continue
                    concept_key = concept_by_model_column_id.get(mid)
                    if not concept_key:
                        continue
                    selected_columns.append({"concept_key": concept_key, "model_column_id": mid})
                    continue
                if isinstance(item, dict):
                    mid = _to_int(item.get("model_column_id"))
                    if mid is None:
                        mid = _to_int(item.get("modelColumnId"))
                    if mid is None:
                        continue
                    concept_key = str(item.get("concept_key") or item.get("conceptKey") or "").strip().upper()
                    if concept_key == "":
                        concept_key = concept_by_model_column_id.get(mid, "")
                    if concept_key == "":
                        continue
                    selected_columns.append({"concept_key": concept_key, "model_column_id": mid})
        normalized["selected_columns"] = selected_columns

        filters: List[Dict[str, Any]] = []
        raw_filters = normalized.get("filters")
        if isinstance(raw_filters, list):
            for item in raw_filters:
                if not isinstance(item, dict):
                    continue
                mid = _to_int(item.get("model_column_id"))
                if mid is None:
                    mid = _to_int(item.get("modelColumnId"))
                concept_key = str(item.get("concept_key") or item.get("conceptKey") or "").strip().upper()
                if concept_key == "" and mid is not None:
                    concept_key = concept_by_model_column_id.get(mid, "")
                if concept_key == "":
                    column_expr = str(item.get("column") or "").strip().lower()
                    if column_expr:
                        parts = [p for p in column_expr.split(".") if p]
                        if len(parts) >= 2:
                            concept_key = concept_by_table_column.get((parts[-2], parts[-1]), "")
                        if concept_key == "" and parts:
                            concept_key = concept_by_column_name.get(parts[-1]) or ""
                op = str(item.get("op") or item.get("operator") or "").strip()
                if concept_key == "" or op == "":
                    continue
                filters.append(
                    {
                        "concept_key": concept_key,
                        "op": op,
                        "value": item.get("value"),
                    }
                )
        normalized["filters"] = filters

        raw_join_plan = normalized.get("join_plan")
        if isinstance(raw_join_plan, list):
            normalized["join_plan"] = {"joins": raw_join_plan}
        elif isinstance(raw_join_plan, dict):
            normalized["join_plan"] = raw_join_plan
        else:
            normalized["join_plan"] = {}

        raw_notes = normalized.get("notes")
        if isinstance(raw_notes, str):
            notes = [raw_notes.strip()] if raw_notes.strip() else []
        elif isinstance(raw_notes, list):
            notes = [str(n).strip() for n in raw_notes if str(n).strip()]
        else:
            notes = []
        normalized["notes"] = notes

        confidence = _to_float(normalized.get("confidence"))
        if confidence is None:
            confidence = 0.5
        normalized["confidence"] = max(0.0, min(1.0, confidence))
        return normalized

    @staticmethod
    def extract_from_table_hint(sql_json: Dict[str, Any]) -> Optional[str]:
        if not isinstance(sql_json, dict):
            return None
        raw_from = sql_json.get("from")
        if isinstance(raw_from, dict):
            raw_from = raw_from.get("value")
        if not isinstance(raw_from, str):
            return None
        text = raw_from.strip()
        if text == "":
            return None
        text = text.split()[-1]
        if "." in text:
            text = text.split(".")[-1]
        return text.strip().lower() or None

    @staticmethod
    def resolve_filter_column(
        *,
        concept_key: str,
        selected_rows_by_concept: Dict[str, List[Dict[str, Any]]],
        candidate_by_concept: Dict[str, List[Dict[str, Any]]],
        table_hint: Optional[str],
        policy_service: Optional[PlannerSemanticJoinPolicyService] = None,
    ) -> Optional[Dict[str, Any]]:
        selected_rows = [dict(row, __selected__=True) for row in list(selected_rows_by_concept.get(concept_key) or [])]
        candidate_rows = [dict(row, __selected__=False) for row in list(candidate_by_concept.get(concept_key) or [])]
        all_rows = selected_rows + candidate_rows

        if table_hint:
            for row in all_rows:
                if str(row.get("table_name") or "").strip().lower() == table_hint:
                    return row

        if not all_rows:
            return None

        all_rows.sort(
            key=lambda row: SqlJsonBuilder.filter_column_rank(
                concept_key=concept_key,
                row=row,
                policy_service=policy_service,
            )
        )
        return all_rows[0]

    @staticmethod
    def filter_column_rank(
        *,
        concept_key: str,
        row: Dict[str, Any],
        policy_service: Optional[PlannerSemanticJoinPolicyService] = None,
    ) -> Tuple[int, int, float, int]:
        service = policy_service or PlannerSemanticJoinPolicyService(enable_db_lookup=False)
        return service.filter_column_rank(concept_key=concept_key, row=row)

    @staticmethod
    def normalize_filter_operator(op: str) -> Optional[str]:
        value = str(op or "").strip().lower()
        mapping = {
            "=": "equals",
            "==": "equals",
            "eq": "equals",
            "equals": "equals",
            "contains": "contains",
            "like": "contains",
            "starts_with": "starts_with",
            "startswith": "starts_with",
            "prefix": "starts_with",
            "in": "in",
            "between": "between",
            "gt": "gt",
            ">": "gt",
            "lt": "lt",
            "<": "lt",
            "!=": "not_equals",
            "<>": "not_equals",
            "ne": "not_equals",
            "not_equal": "not_equals",
            "not_equals": "not_equals",
        }
        return mapping.get(value)

    @staticmethod
    def inject_count_aggregation(
        *,
        sql_json: Dict[str, Any],
        metric_columns: Sequence[Dict[str, Any]],
        dimension_columns: Sequence[Dict[str, Any]],
    ) -> Dict[str, Any]:
        out = dict(sql_json or {})
        aggs = out.get("aggs")
        if not isinstance(aggs, dict):
            aggs = {"enabled": True, "groupBy": [], "metrics": []}
            out["aggs"] = aggs
        aggs["enabled"] = True
        if not isinstance(aggs.get("groupBy"), list):
            aggs["groupBy"] = []
        if not isinstance(aggs.get("metrics"), list):
            aggs["metrics"] = []

        group_seen = {
            (_to_int(item.get("modelColumnId")), str(item.get("columnName") or "").lower())
            for item in aggs.get("groupBy", [])
            if isinstance(item, dict)
        }
        for row in dimension_columns:
            field = {
                "modelColumnId": _to_int(row.get("model_column_id")),
                "workspaceTableId": _to_int(row.get("workspace_table_id")),
                "columnName": row.get("column_name"),
                "exprId": None,
                "alias": None,
            }
            signature = (_to_int(field.get("modelColumnId")), str(field.get("columnName") or "").lower())
            if signature not in group_seen and field["modelColumnId"] is not None and field["columnName"]:
                aggs["groupBy"].append(field)
                group_seen.add(signature)

        if not aggs["metrics"]:
            metric_row = metric_columns[0] if metric_columns else None
            metric_field = None
            fn = "count"
            if isinstance(metric_row, dict):
                candidate_field = {
                    "modelColumnId": _to_int(metric_row.get("model_column_id")),
                    "workspaceTableId": _to_int(metric_row.get("workspace_table_id")),
                    "columnName": metric_row.get("column_name"),
                    "exprId": None,
                    "alias": None,
                }
                if (
                    isinstance(candidate_field.get("columnName"), str)
                    and str(candidate_field.get("columnName") or "").strip()
                ):
                    metric_field = candidate_field
                if str(metric_row.get("metric_agg") or "").strip().lower():
                    fn = str(metric_row.get("metric_agg") or "").strip().lower()
                if "student" in str(metric_row.get("concept_key") or "").lower():
                    fn = "count_distinct"
            aggs["metrics"].append(
                {
                    "id": "semantic_plan_metric_count",
                    "fn": fn,
                    "field": metric_field,
                    "label": str((metric_row or {}).get("metric_label") or "count") if isinstance(metric_row, dict) else "count",
                }
            )
        return out

    @staticmethod
    def apply_skeleton_constraints(
        *,
        payload: Dict[str, Any],
        skeleton: Dict[str, Any],
        slot_intent: SlotDrivenIntent,
        prompt: str,
    ) -> Dict[str, Any]:
        out = dict(payload or {})
        if slot_intent.implies_count_metric(prompt):
            if not isinstance(out.get("sql_json"), dict):
                out["sql_json"] = dict(skeleton.get("sql_json") or {})
            else:
                sql_json = dict(out.get("sql_json") or {})
                if not isinstance(sql_json.get("aggs"), dict) or not list((sql_json.get("aggs") or {}).get("metrics") or []):
                    sql_json["aggs"] = (skeleton.get("sql_json") or {}).get("aggs")
                out["sql_json"] = sql_json
                skeleton_selected = [dict(item) for item in list(skeleton.get("selected_columns") or []) if isinstance(item, dict)]
                selected = [dict(item) for item in list(out.get("selected_columns") or []) if isinstance(item, dict)]
                seen = {(_to_int(item.get("model_column_id")), str(item.get("concept_key") or "").upper()) for item in selected}
                for item in skeleton_selected:
                    key = (_to_int(item.get("model_column_id")), str(item.get("concept_key") or "").upper())
                    if key in seen:
                        continue
                    selected.append(item)
                    seen.add(key)
                out["selected_columns"] = selected
        return out

    @staticmethod
    def collect_illegal_model_column_ids(*, sql_json: Dict[str, Any], allowed_model_column_ids: set[int]) -> set[int]:
        seen: set[int] = set()

        def _check_field(field: Any) -> None:
            if not isinstance(field, dict):
                return
            mid = _to_int(field.get("modelColumnId"))
            if mid is not None and mid not in allowed_model_column_ids:
                seen.add(mid)

        for column in list(sql_json.get("columns") or []):
            if isinstance(column, dict):
                _check_field(column.get("field"))
        for sort in list(sql_json.get("sorting") or []):
            if isinstance(sort, dict):
                _check_field(sort.get("col"))

        def _walk_filter(node: Any) -> None:
            if not isinstance(node, dict):
                return
            node_type = str(node.get("type") or "").strip().lower()
            if node_type == "condition":
                _check_field(node.get("field"))
                return
            if node_type == "group":
                for child in list(node.get("children") or []):
                    _walk_filter(child)

        _walk_filter(sql_json.get("filters"))

        aggs = sql_json.get("aggs")
        if isinstance(aggs, dict):
            for group in list(aggs.get("groupBy") or []):
                _check_field(group)
            for metric in list(aggs.get("metrics") or []):
                if isinstance(metric, dict):
                    _check_field(metric.get("field"))
        return seen

    @staticmethod
    def enforce_count_commercial_rule(
        *,
        llm_plan: Dict[str, Any],
        role_guardrails: Dict[str, Any],
    ) -> Dict[str, Any]:
        out = dict(llm_plan or {})
        sql_json = dict(out.get("sql_json") or {})
        sql_json = SqlJsonBuilder.inject_count_aggregation(
            sql_json=sql_json,
            metric_columns=list(role_guardrails.get("metric_columns") or []),
            dimension_columns=list(role_guardrails.get("dimension_columns") or []),
        )
        out["sql_json"] = sql_json
        return out
