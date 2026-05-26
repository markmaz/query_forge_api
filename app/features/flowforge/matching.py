from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


SUPPORTED_SELECTION_STRATEGIES = {"top_ranked", "highest_score", "balanced_top_ranked"}

SUPPORTED_OPERATORS = {
    "equals",
    "not_equals",
    "in",
    "not_in",
    "contains",
    "not_contains",
    "exists",
    "not_exists",
    "gt",
    "gte",
    "lt",
    "lte",
    "between",
    "overlaps",
    "matches_context",
    "contains_context",
}


@dataclass(frozen=True)
class RuleResult:
    passed: bool
    reason: str | None = None


class MatchingPolicyEngine:
    def validate_policy(self, policy: dict[str, Any]) -> dict[str, Any]:
        errors: list[str] = []
        warnings: list[str] = []
        if not isinstance(policy, dict):
            return {"valid": False, "errors": ["policy must be an object."], "warnings": []}
        if policy.get("version") != 1:
            errors.append("policy.version must be 1.")
        for section in ("eligibility", "scoring"):
            rules = policy.get(section, [])
            if rules is None:
                continue
            if not isinstance(rules, list):
                errors.append(f"{section} must be an array.")
                continue
            for index, rule in enumerate(rules):
                self._validate_rule(rule, section=section, index=index, errors=errors)
        self._validate_selection(policy.get("selection"), errors=errors)
        return {"valid": not errors, "errors": errors, "warnings": warnings}

    def simulate(
        self,
        *,
        policy: dict[str, Any],
        resources: list[dict[str, Any]],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        validation = self.validate_policy(policy)
        if not validation["valid"]:
            return {
                **validation,
                "eligible_candidates": [],
                "excluded_candidates": [],
                "ranked_candidates": [],
                "selected_candidate": None,
                "no_match_reason": "policy_invalid",
            }

        eligible_candidates: list[dict[str, Any]] = []
        excluded_candidates: list[dict[str, Any]] = []
        for resource in resources:
            candidate = self._evaluate_candidate(policy=policy, resource=resource, context=context)
            if candidate["included"]:
                eligible_candidates.append(candidate)
            else:
                excluded_candidates.append(candidate)

        ranked_candidates = self._rank_candidates(policy=policy, candidates=eligible_candidates)
        for index, candidate in enumerate(ranked_candidates, start=1):
            candidate["rank_position"] = index
        selected_candidate = ranked_candidates[0] if ranked_candidates else None
        if selected_candidate:
            selected_candidate["selected"] = True
        return {
            "valid": True,
            "errors": [],
            "warnings": validation["warnings"],
            "eligible_candidates": eligible_candidates,
            "excluded_candidates": excluded_candidates,
            "ranked_candidates": ranked_candidates,
            "selected_candidate": selected_candidate,
            "no_match_reason": None if selected_candidate else "no_eligible_candidates",
        }

    def _validate_selection(self, selection: Any, *, errors: list[str]) -> None:
        if selection is None:
            return
        if not isinstance(selection, dict):
            errors.append("selection must be an object.")
            return
        strategy = str(selection.get("strategy") or "top_ranked").strip()
        if strategy not in SUPPORTED_SELECTION_STRATEGIES:
            errors.append(f"selection.strategy '{strategy}' is not supported.")
        fairness = selection.get("fairness", {})
        if fairness is None:
            return
        if not isinstance(fairness, dict):
            errors.append("selection.fairness must be an object.")
            return
        if "within_score_delta" in fairness:
            try:
                if float(fairness.get("within_score_delta")) < 0:
                    errors.append("selection.fairness.within_score_delta must be greater than or equal to 0.")
            except (TypeError, ValueError):
                errors.append("selection.fairness.within_score_delta must be numeric.")

    def _validate_rule(self, rule: Any, *, section: str, index: int, errors: list[str]) -> None:
        prefix = f"{section}[{index}]"
        if not isinstance(rule, dict):
            errors.append(f"{prefix} must be an object.")
            return
        if not str(rule.get("field") or "").strip():
            errors.append(f"{prefix}.field is required.")
        operator = str(rule.get("operator") or "").strip()
        if not operator:
            errors.append(f"{prefix}.operator is required.")
        elif operator not in SUPPORTED_OPERATORS:
            errors.append(f"{prefix}.operator '{operator}' is not supported.")
        if operator in {"matches_context", "contains_context"} and not str(rule.get("context_field") or "").strip():
            errors.append(f"{prefix}.context_field is required for {operator}.")
        if operator == "between" and (not isinstance(rule.get("value"), list) or len(rule.get("value")) != 2):
            errors.append(f"{prefix}.value must be a two-item array for between.")
        if operator in {"in", "not_in", "overlaps"} and not isinstance(rule.get("value"), list):
            errors.append(f"{prefix}.value must be an array for {operator}.")
        if section == "scoring":
            try:
                float(rule.get("weight", 0))
            except (TypeError, ValueError):
                errors.append(f"{prefix}.weight must be numeric.")

    def _evaluate_candidate(
        self,
        *,
        policy: dict[str, Any],
        resource: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        source_record_key = str(resource.get("source_record_key") or resource.get("id") or "").strip()
        display_name = resource.get("display_name")
        exclusion_reasons: list[str] = []
        eligibility_results: list[dict[str, Any]] = []
        for rule in policy.get("eligibility", []) or []:
            result = self._evaluate_rule(rule=rule, resource=resource, context=context)
            eligibility_results.append(
                {
                    "rule_id": rule.get("id"),
                    "passed": result.passed,
                    "reason": result.reason,
                }
            )
            if not result.passed:
                exclusion_reasons.append(result.reason or f"Rule {rule.get('id') or rule.get('field')} did not pass.")

        included = not exclusion_reasons
        score = 0.0
        score_breakdown: list[dict[str, Any]] = []
        if included:
            for rule in policy.get("scoring", []) or []:
                result = self._evaluate_rule(rule=rule, resource=resource, context=context)
                weight = float(rule.get("weight") or 0)
                applied = result.passed
                if applied:
                    score += weight
                score_breakdown.append(
                    {
                        "rule_id": rule.get("id"),
                        "applied": applied,
                        "weight": weight,
                        "reason": result.reason,
                    }
                )

        return {
            "source_record_key": source_record_key,
            "display_name": display_name,
            "included": included,
            "excluded": not included,
            "selected": False,
            "rank_position": None,
            "score": score,
            "active_offer_count": self._number_or_default(self._resolve_field(resource, "active_offer_count"), default=0),
            "last_offered_at": self._resolve_field(resource, "last_offered_at"),
            "eligibility_result": eligibility_results,
            "score_breakdown": score_breakdown,
            "exclusion_reasons": exclusion_reasons,
            "explanation": self._candidate_explanation(
                included=included,
                score=score,
                exclusion_reasons=exclusion_reasons,
                score_breakdown=score_breakdown,
            ),
        }

    def _rank_candidates(self, *, policy: dict[str, Any], candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
        selection = policy.get("selection") if isinstance(policy.get("selection"), dict) else {}
        strategy = str(selection.get("strategy") or "top_ranked").strip()
        if strategy == "highest_score":
            strategy = "top_ranked"
        if strategy != "balanced_top_ranked":
            return sorted(candidates, key=self._top_ranked_sort_key)
        return self._rank_balanced_top_candidates(candidates=candidates, selection=selection)

    def _rank_balanced_top_candidates(
        self,
        *,
        candidates: list[dict[str, Any]],
        selection: dict[str, Any],
    ) -> list[dict[str, Any]]:
        top_ranked = sorted(candidates, key=self._top_ranked_sort_key)
        if not top_ranked:
            return []
        fairness = selection.get("fairness") if isinstance(selection.get("fairness"), dict) else {}
        within_score_delta = self._number_or_default(fairness.get("within_score_delta"), default=5)
        top_score = float(top_ranked[0].get("score") or 0)
        threshold = top_score - max(within_score_delta, 0)
        top_pool = [candidate for candidate in top_ranked if float(candidate.get("score") or 0) >= threshold]
        remaining = [candidate for candidate in top_ranked if float(candidate.get("score") or 0) < threshold]
        return sorted(top_pool, key=lambda row: self._balanced_sort_key(row, fairness=fairness)) + remaining

    def _top_ranked_sort_key(self, row: dict[str, Any]) -> tuple[float, str, str]:
        return (-float(row.get("score") or 0), str(row.get("display_name") or ""), str(row["source_record_key"]))

    def _balanced_sort_key(self, row: dict[str, Any], *, fairness: dict[str, Any]) -> tuple[float, int, float, float, str, str]:
        active_offer_key = self._number_or_default(row.get("active_offer_count"), default=0)
        if fairness.get("penalize_active_offers", True) is False:
            active_offer_key = 0
        last_offered_timestamp = self._timestamp(row.get("last_offered_at"))
        last_offered_key = (1, last_offered_timestamp or 0)
        if fairness.get("prefer_least_recently_offered", True) is False:
            last_offered_key = (0, 0)
        return (
            active_offer_key,
            last_offered_key[0],
            last_offered_key[1],
            -float(row.get("score") or 0),
            str(row.get("display_name") or ""),
            str(row["source_record_key"]),
        )

    def _candidate_explanation(
        self,
        *,
        included: bool,
        score: float,
        exclusion_reasons: list[str],
        score_breakdown: list[dict[str, Any]],
    ) -> str:
        if not included:
            return "Excluded: " + "; ".join(exclusion_reasons)
        applied = [str(row.get("reason") or row.get("rule_id")) for row in score_breakdown if row.get("applied")]
        if not applied:
            return f"Included with score {score:g}."
        return f"Included with score {score:g}: " + "; ".join(applied)

    def _evaluate_rule(self, *, rule: dict[str, Any], resource: dict[str, Any], context: dict[str, Any]) -> RuleResult:
        field = str(rule.get("field") or "").strip()
        operator = str(rule.get("operator") or "").strip()
        value = rule.get("value")
        field_value = self._resolve_field(resource, field)
        context_value = self._resolve_field(context, str(rule.get("context_field") or ""))
        passed = self._apply_operator(operator=operator, field_value=field_value, value=value, context_value=context_value)
        reason = str(rule.get("reason") or rule.get("id") or field or operator)
        return RuleResult(passed=passed, reason=reason)

    def _resolve_field(self, source: dict[str, Any], field: str) -> Any:
        if not field:
            return None
        if field in source:
            return source.get(field)
        for container_key in ("attributes", "normalized_profile", "attributes_json", "normalized_profile_json"):
            container = source.get(container_key)
            if isinstance(container, dict) and field in container:
                return container.get(field)
        return None

    def _number_or_default(self, value: Any, *, default: float) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _timestamp(self, value: Any) -> float | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value.timestamp()
        clean_value = str(value).strip()
        if not clean_value:
            return None
        try:
            return datetime.fromisoformat(clean_value.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return None

    def _apply_operator(self, *, operator: str, field_value: Any, value: Any, context_value: Any) -> bool:
        if operator == "exists":
            return self._exists(field_value)
        if operator == "not_exists":
            return not self._exists(field_value)
        if not self._exists(field_value):
            return False
        if operator == "equals":
            return self._eq(field_value, value)
        if operator == "not_equals":
            return not self._eq(field_value, value)
        if operator == "in":
            return self._in(field_value, value)
        if operator == "not_in":
            return not self._in(field_value, value)
        if operator == "contains":
            return self._contains(field_value, value)
        if operator == "not_contains":
            return not self._contains(field_value, value)
        if operator == "gt":
            return self._compare(field_value, value, ">")
        if operator == "gte":
            return self._compare(field_value, value, ">=")
        if operator == "lt":
            return self._compare(field_value, value, "<")
        if operator == "lte":
            return self._compare(field_value, value, "<=")
        if operator == "between":
            return self._between(field_value, value)
        if operator == "overlaps":
            return self._overlaps(field_value, value)
        if operator == "matches_context":
            return self._eq(field_value, context_value)
        if operator == "contains_context":
            return self._contains(field_value, context_value)
        return False

    def _exists(self, value: Any) -> bool:
        if value is None:
            return False
        if isinstance(value, str):
            return bool(value.strip())
        if isinstance(value, (list, tuple, set, dict)):
            return bool(value)
        return True

    def _eq(self, left: Any, right: Any) -> bool:
        if isinstance(left, (list, tuple, set)):
            return any(self._eq(item, right) for item in left)
        return str(left).strip().lower() == str(right).strip().lower()

    def _in(self, field_value: Any, options: Any) -> bool:
        if not isinstance(options, list):
            return False
        if isinstance(field_value, (list, tuple, set)):
            return any(self._eq(item, option) for item in field_value for option in options)
        return any(self._eq(field_value, option) for option in options)

    def _contains(self, field_value: Any, value: Any) -> bool:
        if isinstance(field_value, (list, tuple, set)):
            if isinstance(value, (list, tuple, set)):
                return any(self._eq(item, option) for item in field_value for option in value)
            return any(self._eq(item, value) for item in field_value)
        if isinstance(field_value, str):
            if isinstance(value, (list, tuple, set)):
                return any(str(option).strip().lower() in field_value.strip().lower() for option in value)
            return str(value).strip().lower() in field_value.strip().lower()
        return False

    def _compare(self, left: Any, right: Any, operator: str) -> bool:
        try:
            left_num = float(left)
            right_num = float(right)
        except (TypeError, ValueError):
            return False
        if operator == ">":
            return left_num > right_num
        if operator == ">=":
            return left_num >= right_num
        if operator == "<":
            return left_num < right_num
        if operator == "<=":
            return left_num <= right_num
        return False

    def _between(self, field_value: Any, bounds: Any) -> bool:
        if not isinstance(bounds, list) or len(bounds) != 2:
            return False
        try:
            field_num = float(field_value)
            lower = float(bounds[0])
            upper = float(bounds[1])
        except (TypeError, ValueError):
            return False
        return lower <= field_num <= upper

    def _overlaps(self, field_value: Any, options: Any) -> bool:
        if not isinstance(options, list) or not isinstance(field_value, (list, tuple, set)):
            return False
        return any(self._eq(item, option) for item in field_value for option in options)
