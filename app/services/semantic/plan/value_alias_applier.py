from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.ports.sql_executor import ForgeQueryPort
from app.services.semantic.value_alias_service import canonicalize_value
from app.services.semantic.plan.utils import _in_clause

JSON_ROUNDTRIP_FALLBACK_ERRORS = (TypeError, ValueError)


class ValueAliasApplier:
    def __init__(
        self,
        *,
        sql: Optional[ForgeQueryPort] = None,
    ) -> None:
        self._sql = sql or ForgeMetaSQL()

    def apply(self, *, vertical_norm: str, llm_plan: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(llm_plan, dict):
            return llm_plan
        raw_filters = llm_plan.get("filters")
        if not isinstance(raw_filters, list) or not raw_filters:
            return llm_plan

        concept_keys: List[str] = []
        for item in raw_filters:
            if not isinstance(item, dict):
                continue
            key = str(item.get("concept_key") or "").strip().upper()
            if key and key not in concept_keys:
                concept_keys.append(key)
        if not concept_keys:
            return llm_plan

        rules_by_concept = self._load_value_alias_rules(vertical_norm=vertical_norm, concept_keys=concept_keys)
        normalized_filters, changed = ValueAliasApplier._normalize_filters_with_value_aliases(raw_filters, rules_by_concept)
        normalized_filters, canonical_changed = ValueAliasApplier._canonicalize_filters_with_static_aliases(
            filters=normalized_filters,
            vertical_norm=vertical_norm,
        )
        total_changed = changed + canonical_changed
        if total_changed <= 0:
            return llm_plan

        out = dict(llm_plan)
        out["filters"] = normalized_filters
        out["sql_json"] = ValueAliasApplier._sync_sql_json_filter_values(llm_plan.get("sql_json"), normalized_filters)
        notes_raw = out.get("notes")
        notes = list(notes_raw) if isinstance(notes_raw, list) else []
        notes.append(f"value_aliases_applied={total_changed}")
        out["notes"] = notes
        return out

    def _load_value_alias_rules(self, *, vertical_norm: str, concept_keys: Sequence[str]) -> Dict[str, List[Dict[str, Any]]]:
        keys = [str(k or "").strip().upper() for k in concept_keys if str(k or "").strip()]
        if not keys:
            return {}
        in_sql, in_params = _in_clause("ck", keys)
        rows = self._sql.execute_query_mappings(
            f"""
            SELECT
              sc.concept_key,
              va.alias_value,
              va.canonical_value,
              va.match_kind,
              va.weight,
              va.vertical_norm
            FROM semantic_value_alias va
            JOIN semantic_concept sc ON sc.id = va.semantic_concept_id
            WHERE sc.concept_key IN ({in_sql})
              AND va.vertical_norm IN (:vertical_norm, 'generic')
            ORDER BY
              CASE WHEN va.vertical_norm = :vertical_norm THEN 0 ELSE 1 END,
              sc.concept_key,
              va.weight DESC,
              va.id ASC
            """,
            {
                **in_params,
                "vertical_norm": str(vertical_norm or "generic").strip().lower() or "generic",
            },
        )
        out: Dict[str, List[Dict[str, Any]]] = {}
        for row in rows:
            key = str(row.get("concept_key") or "").strip().upper()
            if key == "":
                continue
            out.setdefault(key, []).append(dict(row))
        return out

    @staticmethod
    def _normalize_filters_with_value_aliases(
        filters: Sequence[Dict[str, Any]],
        rules_by_concept: Dict[str, List[Dict[str, Any]]],
    ) -> Tuple[List[Dict[str, Any]], int]:
        out: List[Dict[str, Any]] = []
        changed = 0
        for item in filters:
            if not isinstance(item, dict):
                out.append(item)
                continue
            key = str(item.get("concept_key") or "").strip().upper()
            rules = rules_by_concept.get(key, [])
            next_item = dict(item)
            next_value, did_change = ValueAliasApplier._normalize_filter_value_with_rules(item.get("value"), rules)
            if did_change:
                changed += 1
                next_item["value"] = next_value
            out.append(next_item)
        return out, changed

    @staticmethod
    def _normalize_filter_value_with_rules(value: Any, rules: Sequence[Dict[str, Any]]) -> Tuple[Any, bool]:
        if not rules:
            return value, False
        if isinstance(value, str):
            return ValueAliasApplier._apply_value_alias_rules_to_string(value, rules)
        if isinstance(value, list):
            did_change = False
            out: List[Any] = []
            for item in value:
                if isinstance(item, str):
                    normalized, changed = ValueAliasApplier._apply_value_alias_rules_to_string(item, rules)
                    out.append(normalized)
                    did_change = did_change or changed
                else:
                    out.append(item)
            return out, did_change
        return value, False

    @staticmethod
    def _apply_value_alias_rules_to_string(value: str, rules: Sequence[Dict[str, Any]]) -> Tuple[str, bool]:
        source = str(value or "").strip()
        if source == "":
            return value, False
        source_lower = source.lower()

        for rule in rules:
            alias = str(rule.get("alias_value") or "").strip()
            canonical = str(rule.get("canonical_value") or "").strip()
            match_kind = str(rule.get("match_kind") or "contains").strip().lower()
            if alias == "" or canonical == "":
                continue

            alias_lower = alias.lower()
            matched = False
            if match_kind == "exact":
                matched = source_lower == alias_lower
            elif match_kind == "contains":
                matched = alias_lower in source_lower
            elif match_kind == "prefix":
                matched = source_lower.startswith(alias_lower)
            elif match_kind == "regex":
                try:
                    matched = re.search(alias, source, flags=re.IGNORECASE) is not None
                except re.error:
                    matched = False
            if matched:
                return canonical, canonical != value
        return value, False

    @staticmethod
    def _canonicalize_filters_with_static_aliases(
        *,
        filters: Sequence[Dict[str, Any]],
        vertical_norm: str,
    ) -> Tuple[List[Dict[str, Any]], int]:
        out: List[Dict[str, Any]] = []
        changed = 0
        for item in filters:
            if not isinstance(item, dict):
                out.append(item)
                continue
            concept_key = str(item.get("concept_key") or "").strip().upper()
            value = item.get("value")
            if isinstance(value, str) and concept_key:
                canonical = canonicalize_value(concept_key, value, vertical=vertical_norm)
                if canonical and canonical != value:
                    next_item = dict(item)
                    next_item["value"] = canonical
                    out.append(next_item)
                    changed += 1
                    continue
            out.append(dict(item))
        return out, changed

    @staticmethod
    def _sync_sql_json_filter_values(sql_json: Any, filters: Sequence[Dict[str, Any]]) -> Any:
        if not isinstance(sql_json, dict) or not isinstance(filters, Sequence):
            return sql_json
        try:
            out = json.loads(json.dumps(sql_json))
        except JSON_ROUNDTRIP_FALLBACK_ERRORS:
            out = dict(sql_json)

        where_node = out.get("where")
        if isinstance(where_node, list):
            ValueAliasApplier._sync_where_items(where_node, filters)
        elif isinstance(where_node, dict):
            conds = where_node.get("conditions")
            if isinstance(conds, list):
                ValueAliasApplier._sync_where_items(conds, filters)

        filters_node = out.get("filters")
        if isinstance(filters_node, dict):
            conditions: List[Dict[str, Any]] = []
            ValueAliasApplier._collect_filter_conditions(filters_node, conditions)
            for idx, cond in enumerate(conditions):
                if idx >= len(filters):
                    break
                cond["value"] = filters[idx].get("value")
        return out

    @staticmethod
    def _sync_where_items(where_items: List[Any], filters: Sequence[Dict[str, Any]]) -> None:
        for idx, item in enumerate(where_items):
            if idx >= len(filters):
                break
            if not isinstance(item, dict):
                continue
            value = filters[idx].get("value")
            param = item.get("param")
            if isinstance(param, dict):
                param["value"] = value
            elif "value" in item:
                item["value"] = value

    @staticmethod
    def _collect_filter_conditions(node: Dict[str, Any], out: List[Dict[str, Any]]) -> None:
        node_type = str(node.get("type") or "").strip().lower()
        if node_type == "condition":
            out.append(node)
            return
        if node_type != "group":
            return
        for child in node.get("children") or []:
            if isinstance(child, dict):
                ValueAliasApplier._collect_filter_conditions(child, out)
