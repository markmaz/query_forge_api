from __future__ import annotations

from typing import Any


OPERATOR_ALIASES = {
    "eq": "equals",
    "=": "equals",
    "==": "equals",
    "ne": "not_equals",
    "neq": "not_equals",
    "!=": "not_equals",
    "<>": "not_equals",
    "contains_all": "contains",
}


def _clean_string(value: Any) -> str:
    return str(value or "").strip()


def _context_field_from_reference(value: Any) -> str:
    clean_value = _clean_string(value)
    if clean_value.startswith("inputs."):
        return clean_value.removeprefix("inputs.")
    return clean_value


def _operator_for_rule(operator: Any, *, value_from: Any = None) -> str:
    clean_operator = _clean_string(operator).lower()
    if value_from:
        if clean_operator in {"eq", "equals", "=", "==", "matches_context"}:
            return "matches_context"
        if clean_operator in {"contains_any", "contains_all", "contains", "in", "overlaps", "contains_context"}:
            return "contains_context"
    if clean_operator == "contains_any":
        return "overlaps"
    return OPERATOR_ALIASES.get(clean_operator, clean_operator)


def _list_value(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, (tuple, set)):
        return list(value)
    if isinstance(value, str) and "," in value:
        return [item.strip() for item in value.split(",") if item.strip()]
    return [value]


def _field_key(field: Any) -> str:
    if isinstance(field, dict):
        return _clean_string(field.get("key") or field.get("path") or field.get("name"))
    return _clean_string(field)


def _field_label(field: Any) -> str:
    if isinstance(field, dict):
        return _clean_string(field.get("label") or field.get("display_name") or field.get("key") or field.get("path"))
    return _clean_string(field)


def _context_fields_from_intake_fields(intake_fields: list[Any]) -> list[dict[str, Any]]:
    context_fields: list[dict[str, Any]] = []
    seen: set[str] = set()
    for field in intake_fields:
        key = _field_key(field)
        if not key or key in seen:
            continue
        seen.add(key)
        context_fields.append(
            {
                "key": key,
                "label": _field_label(field) or key,
                "type": field.get("type", "unknown") if isinstance(field, dict) else "unknown",
            }
        )
    return context_fields


def _merge_context_fields(context_fields: list[Any], intake_fields: list[Any]) -> list[Any]:
    merged: list[Any] = []
    seen: set[str] = set()
    for field in [*context_fields, *_context_fields_from_intake_fields(intake_fields)]:
        key = _field_key(field)
        if not key or key in seen:
            continue
        seen.add(key)
        merged.append(field)
    return merged


def _matching_field_key(fields: list[Any], needles: tuple[str, ...], *, fallback: str) -> str:
    for field in fields:
        key = _field_key(field)
        label = _field_label(field)
        haystack = f"{key} {label}".lower()
        if key and any(needle in haystack for needle in needles):
            return key
    return fallback


def _normalize_rule(rule: dict[str, Any], *, section: str, index: int) -> dict[str, Any]:
    condition = rule.get("when") if isinstance(rule.get("when"), dict) else rule
    value_from = condition.get("value_from") or rule.get("value_from")
    context_field = condition.get("context_field") or rule.get("context_field")
    operator = _operator_for_rule(
        condition.get("operator") or condition.get("op") or rule.get("operator") or rule.get("op"),
        value_from=value_from,
    )
    normalized: dict[str, Any] = {
        "id": _clean_string(rule.get("id") or condition.get("id") or f"{section}-{index + 1}"),
        "field": _clean_string(condition.get("field")),
        "operator": operator,
    }
    reason = rule.get("reason") or rule.get("name") or condition.get("reason")
    if _clean_string(reason):
        normalized["reason"] = _clean_string(reason)
    if value_from or context_field:
        normalized["context_field"] = _context_field_from_reference(value_from or context_field)
    elif "value" in condition:
        value = condition.get("value")
        if operator in {"in", "not_in", "overlaps"}:
            value = _list_value(value)
        normalized["value"] = value
    if section == "scoring":
        normalized["weight"] = rule.get("weight", rule.get("points", 0))
    return normalized


def _normalize_rules(section_value: Any, *, section: str) -> list[dict[str, Any]]:
    if isinstance(section_value, list):
        rules = section_value
    elif isinstance(section_value, dict):
        if isinstance(section_value.get("rules"), list):
            rules = section_value["rules"]
        elif isinstance(section_value.get("all"), list):
            rules = section_value["all"]
        elif isinstance(section_value.get("any"), list):
            rules = section_value["any"]
        else:
            rules = []
    else:
        rules = []
    return [_normalize_rule(rule, section=section, index=index) for index, rule in enumerate(rules) if isinstance(rule, dict)]


def normalize_generated_matching_policy(policy: dict[str, Any], *, resource_set_id: int | None = None) -> dict[str, Any]:
    normalized = dict(policy)
    normalized["version"] = policy.get("version", 1)
    if resource_set_id is not None:
        normalized["resource_set_id"] = resource_set_id
    if "eligibility" in policy:
        normalized["eligibility"] = _normalize_rules(policy.get("eligibility"), section="eligibility")
    if "scoring" in policy:
        normalized["scoring"] = _normalize_rules(policy.get("scoring"), section="scoring")
    return normalized


class MatchingPolicyDraftGenerator:
    """Generates deterministic matching-policy drafts from plain-language instructions."""

    def __init__(self, *, llm_client: Any | None = None) -> None:
        self._llm_client = llm_client

    def generate(
        self,
        *,
        prompt: str,
        resource_set_id: int,
        resource_fields: list[Any] | None = None,
        context_fields: list[Any] | None = None,
        intake_source: dict[str, Any] | None = None,
        intake_fields: list[Any] | None = None,
        use_llm: bool = False,
    ) -> dict[str, Any]:
        clean_prompt = str(prompt or "").strip()
        merged_context_fields = _merge_context_fields(context_fields or [], intake_fields or [])
        if use_llm and self._llm_client is not None:
            return self._generate_with_llm(
                prompt=clean_prompt,
                resource_set_id=resource_set_id,
                resource_fields=resource_fields or [],
                context_fields=merged_context_fields,
                intake_source=intake_source,
                intake_fields=intake_fields or [],
            )
        return self._generate_heuristic(
            prompt=clean_prompt,
            resource_set_id=resource_set_id,
            resource_fields=resource_fields or [],
            context_fields=merged_context_fields,
            intake_source=intake_source,
            intake_fields=intake_fields or [],
        )

    def _generate_with_llm(
        self,
        *,
        prompt: str,
        resource_set_id: int,
        resource_fields: list[Any],
        context_fields: list[Any],
        intake_source: dict[str, Any] | None,
        intake_fields: list[Any],
    ) -> dict[str, Any]:
        payload = self._llm_client.chat_json(
            system_prompt=(
                "You generate Workflow Studio matching policy JSON. Return JSON only with keys "
                "policy and plain_language_summary. The policy must use version 1. Return policy.eligibility "
                "and policy.scoring as arrays. Use deterministic rules, no code, no scripts, and only "
                "supported operators: equals, not_equals, in, not_in, contains, not_contains, exists, "
                "not_exists, gt, gte, lt, lte, between, overlaps, matches_context, contains_context. "
                "For runtime inputs, use context_field instead of value_from. Only use context_field values "
                "listed in the allowed intake/runtime context fields."
            ),
            user_prompt=(
                f"Resource set id: {resource_set_id}\n"
                f"Allowed resource fields: {resource_fields}\n"
                f"Optional intake source: {intake_source or {}}\n"
                f"Allowed intake fields: {intake_fields}\n"
                f"Allowed intake/runtime context fields: {context_fields}\n"
                f"Routing instructions: {prompt}"
            ),
            response_format=True,
            retry_invalid_schema=True,
            max_tokens=1200,
        )
        policy = payload.get("policy") if isinstance(payload.get("policy"), dict) else payload
        if isinstance(policy, dict):
            policy = normalize_generated_matching_policy(policy, resource_set_id=resource_set_id)
            policy["inputs"] = {
                "intake_source": intake_source or {},
                "intake_fields": intake_fields,
                "context_fields": context_fields,
            }
        return {
            "generated_policy": policy if isinstance(policy, dict) else {},
            "plain_language_summary": str(payload.get("plain_language_summary") or "").strip(),
            "model_provider": "configured_llm",
            "model_name": str(getattr(self._llm_client, "_model", "") or "").strip() or None,
            "draft_source": "llm",
        }

    def _generate_heuristic(
        self,
        *,
        prompt: str,
        resource_set_id: int,
        resource_fields: list[Any],
        context_fields: list[Any],
        intake_source: dict[str, Any] | None,
        intake_fields: list[Any],
    ) -> dict[str, Any]:
        lower_prompt = prompt.lower()
        eligibility: list[dict[str, Any]] = [
            {
                "id": "eligible-active",
                "field": "effective_status",
                "operator": "equals",
                "value": "active",
                "reason": "Resource must be active.",
            }
        ]
        scoring: list[dict[str, Any]] = []
        if "available" in lower_prompt or "capacity" in lower_prompt or "workload" in lower_prompt:
            eligibility.append(
                {
                    "id": "eligible-capacity-available",
                    "field": "capacity_available",
                    "operator": "gt",
                    "value": 0,
                    "reason": "Resource must have available capacity.",
                }
            )
            scoring.append(
                {
                    "id": "score-capacity",
                    "field": "capacity_available",
                    "operator": "gt",
                    "value": 0,
                    "weight": 5,
                    "reason": "Prefer resources with available capacity.",
                }
            )
        if "language" in lower_prompt:
            scoring.append(
                {
                    "id": "score-language-match",
                    "field": _matching_field_key(resource_fields, ("language",), fallback="languages"),
                    "operator": "contains_context",
                    "context_field": _matching_field_key(context_fields, ("language",), fallback="preferred_language"),
                    "weight": 3,
                    "reason": "Prefer resources matching the requested language.",
                }
            )
        policy = {
            "version": 1,
            "resource_set_id": resource_set_id,
            "eligibility": eligibility,
            "scoring": scoring,
            "selection": {
                "strategy": "balanced_top_ranked",
                "fairness": {
                    "within_score_delta": 0,
                    "penalize_active_offers": True,
                    "prefer_least_recently_offered": True,
                },
            },
            "capacity": {"strategy": "respect_capacity_available"},
            "offer": {},
            "no_match": {"reason": "no_eligible_candidates"},
            "explanations": {"include_rule_reasons": True},
            "inputs": {
                "intake_source": intake_source or {},
                "intake_fields": intake_fields,
                "context_fields": context_fields,
            },
        }
        return {
            "generated_policy": policy,
            "plain_language_summary": (
                "Drafted a deterministic matching policy that requires active resources"
                " and adds capacity/language preferences when requested."
            ),
            "model_provider": "heuristic",
            "model_name": "flowforge-local-draft-generator",
            "draft_source": "heuristic",
        }
