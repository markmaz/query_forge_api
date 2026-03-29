"""Semantic integration helpers extracted from PlannerDomainService.

Owns: alias constraints resolution, grounding bundle building, semester
indicator column resolution, and semantic value-alias filter normalization.
All methods are independently testable via constructor injection.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.config import QF_PLAN_DOMAIN_SEMANTIC_ASSIST_ENABLED
from app.services.planner.semantic_grounding_service import SemanticGroundingService
from app.services.semantic.value_alias_resolution_service import ValueAliasResolutionService

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Module-level constants (local copies to avoid circular imports)
# ---------------------------------------------------------------------------

_SEMESTER_BUCKET_CONCEPT_KEYS: Dict[str, set] = {
    "spring": {
        "SEMESTER_SPRING_FLAG",
        "IS_SPRING",
        "IS_SPRING_BLOCK",
    },
    "fall": {
        "SEMESTER_FALL_FLAG",
        "IS_FALL",
        "IS_FALL_BLOCK",
    },
    "year_round": {
        "SEMESTER_YEAR_ROUND_FLAG",
        "IS_YEAR_ROUND",
        "IS_YEAR_ROUND_BLOCK",
    },
}


# ---------------------------------------------------------------------------
# Module-level helpers (local copies to avoid circular imports)
# ---------------------------------------------------------------------------


def _to_int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except Exception:
        return None


def _norm_key(value: Any) -> str:
    return str(value or "").strip().lower()


def _norm_vertical(value: Any) -> str:
    return str(value or "generic").strip().lower() or "generic"


def _dedupe_constraints(values: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    seen: set = set()
    for item in values:
        if not isinstance(item, Mapping):
            continue
        kind = str(item.get("kind") or "unknown").strip().lower() or "unknown"
        text = " ".join(str(item.get("text") or "").strip().split())
        op = str(item.get("op") or "unknown").strip().lower() or "unknown"
        value_hint = (
            " ".join(str(item.get("value_hint") or "").strip().split())
            if item.get("value_hint") not in (None, "")
            else ""
        )
        notes = (
            " ".join(str(item.get("notes") or "").strip().split())
            if item.get("notes") not in (None, "")
            else ""
        )
        if text == "" and value_hint == "":
            continue
        key = (kind, text.lower(), op, value_hint.lower(), notes.lower())
        if key in seen:
            continue
        seen.add(key)
        out.append(
            {
                "kind": kind,
                "text": text or value_hint,
                "op": op,
                "value_hint": value_hint or None,
                "notes": notes or None,
            }
        )
    return out


def _semester_bucket_from_text(value: Any) -> str:
    raw = str(value or "").strip()
    if raw == "":
        return ""
    upper = raw.upper().replace("-", "_").replace(" ", "_")
    for bucket, concept_keys in _SEMESTER_BUCKET_CONCEPT_KEYS.items():
        if upper in concept_keys:
            return bucket
    token = raw.lower()
    if token == "":
        return ""
    normalized = token.replace("-", "_").replace(" ", "_")
    if any(marker in normalized for marker in ("year_round", "yearround", "yr_round", "yrround")):
        return "year_round"
    if "spring" in normalized or "sping" in normalized:
        return "spring"
    if "fall" in normalized or "autumn" in normalized:
        return "fall"
    return ""


def _infer_semester_indicator_columns_from_capabilities(
    *,
    capabilities: Mapping[str, Any],
) -> Dict[str, str]:
    rows = (
        list(capabilities.get("filter_columns") or [])
        + list(capabilities.get("dimensions") or [])
        + list(capabilities.get("time_columns") or [])
    )
    best: Dict[str, Tuple[float, str]] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        if row.get("filterable") is False:
            continue
        column_key = _norm_key(row.get("column_key"))
        column_name = str(row.get("column_name") or "").strip().lower()
        if column_key == "" or column_name == "":
            continue
        bucket = _semester_bucket_from_text(column_name)
        if bucket == "":
            continue
        score = 0.0
        if column_name.startswith("is_"):
            score += 3.0
        if "block" in column_name:
            score += 1.5
        if "semester" in column_name or "term" in column_name:
            score += 1.0
        semantic_type = str(row.get("semantic_type") or "").strip().lower()
        if semantic_type in {"flag", "boolean"}:
            score += 1.0
        data_type = str(row.get("data_type") or "").strip().lower()
        if any(token in data_type for token in ("bool", "bit", "tinyint")):
            score += 0.5
        current = best.get(bucket)
        if current is None or score > current[0]:
            best[bucket] = (score, column_key)
    return {bucket: value for bucket, (_score, value) in best.items() if value}


def _normalize_filter_value_with_semantic_alias_map(
    *,
    concept_key: str,
    value: Any,
    alias_map: Mapping[Tuple[str, str], Any],
) -> Tuple[Any, bool]:
    normalized_concept_key = str(concept_key or "").strip().upper()
    if normalized_concept_key == "":
        return value, False
    if isinstance(value, str):
        token = value.strip().lower()
        if token == "":
            return value, False
        canonical = alias_map.get((normalized_concept_key, token))
        if canonical is None or canonical == value:
            return value, False
        return canonical, True
    if isinstance(value, list):
        changed = False
        out: List[Any] = []
        for item in value:
            normalized_item, item_changed = _normalize_filter_value_with_semantic_alias_map(
                concept_key=normalized_concept_key,
                value=item,
                alias_map=alias_map,
            )
            out.append(normalized_item)
            changed = changed or item_changed
        return out, changed
    return value, False


def _boolean_like_filter_column_keys(capabilities: Mapping[str, Any]) -> set:
    out: set = set()
    for row in list(capabilities.get("filter_columns") or []):
        if not isinstance(row, Mapping):
            continue
        column_key = _norm_key(row.get("column_key"))
        if column_key == "":
            continue
        semantic_type = str(row.get("semantic_type") or "").strip().lower()
        data_type = str(row.get("data_type") or "").strip().lower()
        if semantic_type in {"flag", "boolean"} or any(
            token in data_type for token in ("bool", "bit", "tinyint")
        ):
            out.add(column_key)
    return out


def _optional_bool_literal(value: Any) -> Optional[bool]:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        if value in (0, 1):
            return bool(value)
        return None
    if isinstance(value, str):
        token = value.strip().lower()
        if token in {"1", "true", "t", "yes", "y", "on"}:
            return True
        if token in {"0", "false", "f", "no", "n", "off"}:
            return False
    return None


def _coerce_boolean_alias_value(value: Any) -> Tuple[Any, bool]:
    if isinstance(value, list):
        changed = False
        out: List[Any] = []
        for item in value:
            normalized_item, item_changed = _coerce_boolean_alias_value(item)
            out.append(normalized_item)
            changed = changed or item_changed
        return out, changed
    normalized = _optional_bool_literal(value)
    if normalized is None:
        return value, False
    if isinstance(value, bool) and value is normalized:
        return value, False
    return normalized, True


# ---------------------------------------------------------------------------
# SemanticIntegrationService
# ---------------------------------------------------------------------------


class SemanticIntegrationService:
    """Encapsulates all semantic-assist operations for the planner domain."""

    def __init__(
        self,
        *,
        value_alias_resolver: Optional[ValueAliasResolutionService] = None,
        semantic_grounding_service: Optional[SemanticGroundingService] = None,
    ) -> None:
        self._value_alias_resolver_svc = value_alias_resolver
        self._semantic_grounding_service_svc = semantic_grounding_service

    # ------------------------------------------------------------------
    # Lazy-init accessors (kept internal; composition root may pass refs)
    # ------------------------------------------------------------------

    def _value_alias_resolver(self) -> ValueAliasResolutionService:
        if self._value_alias_resolver_svc is None:
            self._value_alias_resolver_svc = ValueAliasResolutionService()
        return self._value_alias_resolver_svc

    def _semantic_grounding_service(self) -> SemanticGroundingService:
        if self._semantic_grounding_service_svc is None:
            self._semantic_grounding_service_svc = SemanticGroundingService(
                value_alias_resolver=self._value_alias_resolver(),
            )
        return self._semantic_grounding_service_svc

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def resolve_alias_constraints(
        self,
        *,
        prompt: str,
        vertical_norm: str,
    ) -> List[Dict[str, Any]]:
        """Return deduplicated semantic alias constraints for a prompt.

        Returns an empty list when the feature flag is disabled or when the
        underlying grounding service raises an exception.
        """
        if not QF_PLAN_DOMAIN_SEMANTIC_ASSIST_ENABLED:
            return []
        try:
            constraints = self._semantic_grounding_service().resolve_alias_constraints(
                prompt=prompt,
                vertical_norm=vertical_norm,
            )
        except Exception as exc:
            logger.warning("planner_domain semantic alias constraints failed err=%s", exc)
            return []
        return _dedupe_constraints(constraints)

    def build_grounding_bundle(self, **kwargs: Any) -> Any:
        """Build a semantic grounding bundle via the underlying grounding service."""
        return self._semantic_grounding_service().build_grounding_bundle(**kwargs)

    def resolve_semester_indicator_columns(
        self,
        *,
        workspace_id: str,
        vertical_norm: str,
        capabilities: Mapping[str, Any],
    ) -> Dict[str, str]:
        """Resolve semester indicator column keys from capabilities and semantic concepts."""
        inferred = _infer_semester_indicator_columns_from_capabilities(capabilities=capabilities)
        semantic = self._resolve_semester_indicator_columns_from_semantic_concepts(
            workspace_id=workspace_id,
            vertical_norm=vertical_norm,
            capabilities=capabilities,
        )
        out = dict(inferred)
        out.update(semantic)
        return out

    def normalize_semantic_value_alias_filters(
        self,
        *,
        plan_json: Mapping[str, Any],
        workspace_id: str,
        vertical_norm: str,
        capabilities: Mapping[str, Any],
    ) -> Tuple[Dict[str, Any], List[str], Dict[str, Any]]:
        """Rewrite filter values using the semantic value-alias map.

        Returns (updated_plan, issues, debug_dict).  If no aliases apply the
        original plan is returned unchanged and the debug dict reflects zero
        applied changes.
        """
        if not QF_PLAN_DOMAIN_SEMANTIC_ASSIST_ENABLED:
            return dict(plan_json or {}), [], {"applied": 0, "changes": []}

        raw_filters = plan_json.get("filters")
        if not isinstance(raw_filters, list) or not raw_filters:
            return dict(plan_json or {}), [], {"applied": 0, "changes": []}

        column_to_concept = self._load_filter_column_concept_keys(
            workspace_id=workspace_id,
            vertical_norm=vertical_norm,
            capabilities=capabilities,
        )
        if not column_to_concept:
            return dict(plan_json or {}), [], {"applied": 0, "changes": []}

        boolean_filter_columns = _boolean_like_filter_column_keys(capabilities)
        alias_map = self._load_semantic_value_alias_map(
            vertical_norm=vertical_norm,
            concept_keys=sorted(set(column_to_concept.values())),
        )
        if not alias_map:
            return dict(plan_json or {}), [], {"applied": 0, "changes": []}

        normalized_filters: List[Dict[str, Any]] = []
        issues: List[str] = []
        changes: List[Dict[str, Any]] = []
        for item in raw_filters:
            if not isinstance(item, Mapping):
                normalized_filters.append(dict(item) if isinstance(item, dict) else item)
                continue
            next_item = dict(item)
            column_key = _norm_key(next_item.get("column_key"))
            concept_key = str(column_to_concept.get(column_key) or "").strip().upper()
            if concept_key:
                normalized_value, changed = _normalize_filter_value_with_semantic_alias_map(
                    concept_key=concept_key,
                    value=next_item.get("value"),
                    alias_map=alias_map,
                )
                if changed:
                    coerced_boolean = False
                    if column_key in boolean_filter_columns:
                        normalized_value, coerced_boolean = _coerce_boolean_alias_value(
                            normalized_value
                        )
                    change_row: Dict[str, Any] = {
                        "column_key": column_key,
                        "concept_key": concept_key,
                        "from_value": next_item.get("value"),
                        "to_value": normalized_value,
                    }
                    if coerced_boolean:
                        change_row["coerced_boolean"] = True
                    changes.append(change_row)
                    issues.append(
                        f"semantic_value_alias_normalized:{column_key}:{concept_key}"
                    )
                    next_item["value"] = normalized_value
            normalized_filters.append(next_item)

        if not changes:
            return dict(plan_json or {}), [], {"applied": 0, "changes": []}

        out = dict(plan_json or {})
        out["filters"] = normalized_filters
        return out, issues, {"applied": len(changes), "changes": changes}

    # ------------------------------------------------------------------
    # Private DB-backed helpers
    # ------------------------------------------------------------------

    def _load_filter_column_concept_keys(
        self,
        *,
        workspace_id: str,
        vertical_norm: str,
        capabilities: Mapping[str, Any],
    ) -> Dict[str, str]:
        workspace_to_key: Dict[int, str] = {}
        for row in list(capabilities.get("filter_columns") or []):
            if not isinstance(row, Mapping):
                continue
            column_key = _norm_key(row.get("column_key"))
            workspace_column_id = _to_int(row.get("workspace_column_id")) or _to_int(
                row.get("model_column_id")
            )
            if column_key == "" or workspace_column_id is None:
                continue
            workspace_to_key.setdefault(workspace_column_id, column_key)
        if not workspace_to_key:
            return {}

        out: Dict[str, str] = {}
        direct_rows = self._load_workspace_column_semantic_concepts(
            workspace_id=workspace_id,
            workspace_column_ids=sorted(workspace_to_key.keys()),
        )
        unresolved_ids: List[int] = []
        for workspace_column_id in sorted(workspace_to_key.keys()):
            column_key = workspace_to_key.get(workspace_column_id)
            direct_concept_key = str(direct_rows.get(workspace_column_id) or "").strip().upper()
            if column_key and direct_concept_key:
                out[column_key] = direct_concept_key
                continue
            unresolved_ids.append(workspace_column_id)

        if not unresolved_ids:
            return out

        params: Dict[str, Any] = {
            "vertical_norm": _norm_vertical(vertical_norm),
        }
        placeholders: List[str] = []
        for idx, workspace_column_id in enumerate(unresolved_ids):
            token = f"wcid_{idx}"
            placeholders.append(f":{token}")
            params[token] = int(workspace_column_id)

        sql = f"""
            SELECT
              m.workspace_column_id,
              UPPER(TRIM(sc.concept_key)) AS concept_key
            FROM workspace_column_semantic_concept_map m
            JOIN semantic_concept sc
              ON sc.id = m.semantic_concept_id
            WHERE LOWER(COALESCE(m.vertical_norm, 'generic')) IN (:vertical_norm, 'generic')
              AND m.workspace_column_id IN ({", ".join(placeholders)})
            ORDER BY
              CASE WHEN LOWER(COALESCE(m.vertical_norm, 'generic')) = :vertical_norm THEN 0 ELSE 1 END,
              CASE WHEN LOWER(COALESCE(m.relationship_kind, 'primary')) = 'primary' THEN 0 ELSE 1 END,
              COALESCE(m.weight, 1.0) DESC,
              m.id ASC
        """
        try:
            rows = ForgeMetaSQL().execute_query_mappings(sql, params)
        except Exception as exc:
            logger.warning("planner_domain semantic concept lookup failed err=%s", exc)
            return out

        for row in rows:
            if not isinstance(row, Mapping):
                continue
            workspace_column_id = _to_int(row.get("workspace_column_id"))
            concept_key = str(row.get("concept_key") or "").strip().upper()
            if workspace_column_id is None or concept_key == "":
                continue
            column_key = workspace_to_key.get(workspace_column_id)
            if column_key and column_key not in out:
                out[column_key] = concept_key
        return out

    def _load_workspace_column_semantic_concepts(
        self,
        *,
        workspace_id: str,
        workspace_column_ids: Sequence[int],
    ) -> Dict[int, str]:
        normalized_ids = sorted(
            {int(item) for item in workspace_column_ids if _to_int(item) is not None}
        )
        if not normalized_ids:
            return {}

        params: Dict[str, Any] = {
            "workspace_id": str(workspace_id or "").strip(),
        }
        placeholders: List[str] = []
        for idx, workspace_column_id in enumerate(normalized_ids):
            token = f"wcd_{idx}"
            placeholders.append(f":{token}")
            params[token] = int(workspace_column_id)

        sql = f"""
            SELECT
              wc.id AS workspace_column_id,
              UPPER(TRIM(wc.semantic_concept_key)) AS concept_key
            FROM workspace_column wc
            JOIN workspace_table wt
              ON wt.id = wc.workspace_table_id
             AND wt.workspace_id = :workspace_id
            WHERE wc.id IN ({", ".join(placeholders)})
              AND wc.semantic_concept_key IS NOT NULL
              AND TRIM(wc.semantic_concept_key) <> ''
        """
        try:
            rows = ForgeMetaSQL().execute_query_mappings(sql, params)
        except Exception as exc:
            logger.warning(
                "planner_domain workspace column semantic concept lookup failed err=%s", exc
            )
            return {}

        out: Dict[int, str] = {}
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            workspace_column_id = _to_int(row.get("workspace_column_id"))
            concept_key = str(row.get("concept_key") or "").strip().upper()
            if workspace_column_id is None or concept_key == "":
                continue
            out.setdefault(workspace_column_id, concept_key)
        return out

    def _load_semantic_value_alias_map(
        self,
        *,
        vertical_norm: str,
        concept_keys: Sequence[str],
    ) -> Dict[Tuple[str, str], Any]:
        normalized_keys = sorted(
            {str(key or "").strip().upper() for key in concept_keys if str(key or "").strip()}
        )
        if not normalized_keys:
            return {}

        params: Dict[str, Any] = {
            "vertical_norm": _norm_vertical(vertical_norm),
        }
        placeholders: List[str] = []
        for idx, concept_key in enumerate(normalized_keys):
            token = f"ck_{idx}"
            placeholders.append(f":{token}")
            params[token] = concept_key

        sql = f"""
            SELECT
              UPPER(TRIM(sc.concept_key)) AS concept_key,
              LOWER(TRIM(va.alias_value)) AS alias_value,
              va.canonical_value
            FROM semantic_value_alias va
            JOIN semantic_concept sc
              ON sc.id = va.semantic_concept_id
            WHERE UPPER(TRIM(sc.concept_key)) IN ({", ".join(placeholders)})
              AND LOWER(COALESCE(va.vertical_norm, 'generic')) IN (:vertical_norm, 'generic')
            ORDER BY
              CASE WHEN LOWER(COALESCE(va.vertical_norm, 'generic')) = :vertical_norm THEN 0 ELSE 1 END,
              COALESCE(va.weight, 1.0) DESC,
              va.id ASC
        """
        try:
            rows = ForgeMetaSQL().execute_query_mappings(sql, params)
        except Exception as exc:
            logger.warning("planner_domain semantic value alias lookup failed err=%s", exc)
            return {}

        out: Dict[Tuple[str, str], Any] = {}
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            concept_key = str(row.get("concept_key") or "").strip().upper()
            alias_value = str(row.get("alias_value") or "").strip().lower()
            if concept_key == "" or alias_value == "":
                continue
            out.setdefault((concept_key, alias_value), row.get("canonical_value"))
        return out

    def _resolve_semester_indicator_columns_from_semantic_concepts(
        self,
        *,
        workspace_id: str,
        vertical_norm: str,
        capabilities: Mapping[str, Any],
    ) -> Dict[str, str]:
        if not QF_PLAN_DOMAIN_SEMANTIC_ASSIST_ENABLED:
            return {}

        cap_rows = (
            list(capabilities.get("filter_columns") or [])
            + list(capabilities.get("dimensions") or [])
            + list(capabilities.get("time_columns") or [])
        )
        workspace_to_key: Dict[int, str] = {}
        for row in cap_rows:
            if not isinstance(row, Mapping):
                continue
            key = _norm_key(row.get("column_key"))
            workspace_column_id = _to_int(row.get("workspace_column_id")) or _to_int(
                row.get("model_column_id")
            )
            if key == "" or workspace_column_id is None:
                continue
            if row.get("filterable") is False:
                continue
            workspace_to_key[workspace_column_id] = key
        if not workspace_to_key:
            return {}

        best: Dict[str, Tuple[float, str]] = {}
        direct_rows = self._load_workspace_column_semantic_concepts(
            workspace_id=workspace_id,
            workspace_column_ids=sorted(workspace_to_key.keys()),
        )
        unresolved_ids: List[int] = []
        for workspace_column_id in sorted(workspace_to_key.keys()):
            column_key = workspace_to_key.get(workspace_column_id)
            if not column_key:
                continue
            concept_key = str(direct_rows.get(workspace_column_id) or "")
            bucket = _semester_bucket_from_text(concept_key)
            if bucket == "":
                unresolved_ids.append(workspace_column_id)
                continue
            best[bucket] = (1000.0, column_key)

        if not unresolved_ids:
            return {bucket: value for bucket, (_score, value) in best.items() if value}

        params: Dict[str, Any] = {
            "vertical_norm": _norm_vertical(vertical_norm),
        }
        placeholders: List[str] = []
        for idx, workspace_column_id in enumerate(unresolved_ids):
            token = f"wid_{idx}"
            placeholders.append(f":{token}")
            params[token] = int(workspace_column_id)

        sql = f"""
            SELECT
              m.workspace_column_id,
              UPPER(TRIM(sc.concept_key)) AS concept_key,
              LOWER(COALESCE(sc.semantic_type, '')) AS semantic_type,
              LOWER(COALESCE(m.relationship_kind, 'primary')) AS relationship_kind,
              COALESCE(m.weight, 1.0) AS weight
            FROM workspace_column_semantic_concept_map m
            JOIN semantic_concept sc
              ON sc.id = m.semantic_concept_id
            WHERE LOWER(COALESCE(m.vertical_norm, 'generic')) IN (:vertical_norm, 'generic')
              AND m.workspace_column_id IN ({", ".join(placeholders)})
            ORDER BY
              CASE WHEN LOWER(COALESCE(m.vertical_norm, 'generic')) = :vertical_norm THEN 0 ELSE 1 END,
              CASE WHEN LOWER(COALESCE(m.relationship_kind, 'primary')) = 'primary' THEN 0 ELSE 1 END,
              COALESCE(m.weight, 1.0) DESC,
              m.id ASC
        """
        try:
            rows = ForgeMetaSQL().execute_query_mappings(sql, params)
        except Exception as exc:
            logger.warning(
                "planner_domain semantic semester indicator lookup failed err=%s", exc
            )
            return {bucket: value for bucket, (_score, value) in best.items() if value}

        for row in rows:
            if not isinstance(row, Mapping):
                continue
            workspace_column_id = _to_int(row.get("workspace_column_id"))
            if workspace_column_id is None:
                continue
            column_key = workspace_to_key.get(workspace_column_id)
            if not column_key:
                continue
            concept_key = str(row.get("concept_key") or "")
            bucket = _semester_bucket_from_text(concept_key)
            if bucket == "":
                continue
            score = float(row.get("weight") or 0.0)
            if str(row.get("relationship_kind") or "").strip().lower() == "primary":
                score += 2.0
            if str(row.get("semantic_type") or "").strip().lower() == "flag":
                score += 1.0
            current = best.get(bucket)
            if current is None or score > current[0]:
                best[bucket] = (score, column_key)

        return {bucket: value for bucket, (_score, value) in best.items() if value}
