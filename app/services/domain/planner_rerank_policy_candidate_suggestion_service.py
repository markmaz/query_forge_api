from __future__ import annotations

import json
import re
from typing import Any, Callable, Dict, List, Mapping, Optional

from pydantic import ValidationError

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.config.llm_resolver import ResolvedLLMRuntime, build_llm_client_for_role
from app.constants.llm_roles import LLMRole
from app.exceptions.forge_error import ForgeError
from app.models.domain.planner_rerank_policy import (
    PLANNER_RERANK_CAPABILITY_KEYS,
    PLANNER_RERANK_SIGNAL_KEYS,
    PlannerRerankPolicyCandidateSuggestRequest,
    PlannerRerankPolicyCandidateSuggestionLLMResponse,
    PlannerRerankPolicyRule,
)
from app.ports.sql_executor import ForgeQueryPort
from app.services.domain.planner_domain_capability_service import PlannerDomainCapabilityService
from app.services.domain.planner_rerank_policy_candidate_service import PlannerRerankPolicyCandidateService
from app.services.domains.capabilities_service import DomainCapabilitiesService
from app.services.llm.llm_client import LLMClient
from app.services.planner_domain.prompt_signal_service import PromptSignalService

_SLUG_RE = re.compile(r"[^a-z0-9]+")
LLM_SUGGESTION_FALLBACK_ERRORS = (OSError, RuntimeError, TypeError, ValueError)
LLM_SUGGESTION_VALIDATION_ERRORS = (ValidationError, TypeError, ValueError)


class PlannerRerankPolicyCandidateSuggestionService:
    def __init__(
        self,
        *,
        sql: Optional[ForgeQueryPort] = None,
        prompt_signal_service: Optional[PromptSignalService] = None,
        capability_service: Optional[PlannerDomainCapabilityService] = None,
        domain_capabilities_service: Optional[DomainCapabilitiesService] = None,
        candidate_service: Optional[PlannerRerankPolicyCandidateService] = None,
        llm_client: Optional[LLMClient] = None,
        llm_runtime_builder: Optional[Callable[..., ResolvedLLMRuntime]] = None,
    ) -> None:
        self._sql = sql or ForgeMetaSQL()
        self._signals = prompt_signal_service or PromptSignalService()
        self._planner_capabilities = capability_service or PlannerDomainCapabilityService(sql=self._sql)
        self._domain_capabilities = domain_capabilities_service or DomainCapabilitiesService(sql=self._sql)
        self._candidates = candidate_service or PlannerRerankPolicyCandidateService(sql=self._sql)
        self._explicit_llm = llm_client
        self._llm_runtime_builder = llm_runtime_builder or build_llm_client_for_role

    def suggest_candidate(
        self,
        *,
        workspace_id: str,
        user_id: str,
        payload: Any,
    ) -> Dict[str, Any]:
        req = PlannerRerankPolicyCandidateSuggestRequest.model_validate(payload)
        vertical_norm = "generic"
        prompt_signals = self._signals.extract_signals(prompt=req.prompt)

        expected_domain = self._build_domain_snapshot(
            workspace_id=workspace_id,
            user_id=user_id,
            domain_id=int(req.expected_base_domain_id),
            vertical_norm=vertical_norm,
        )
        observed_domain = None
        if req.observed_base_domain_id is not None:
            observed_domain = self._build_domain_snapshot(
                workspace_id=workspace_id,
                user_id=user_id,
                domain_id=int(req.observed_base_domain_id),
                vertical_norm=vertical_norm,
            )

        llm_client, llm_resolution = self._resolve_llm(
            workspace_id=workspace_id,
            llm_id=req.llm_id,
        )
        suggestion_source_type = "ai_recommendation"
        try:
            suggestion = PlannerRerankPolicyCandidateSuggestionLLMResponse.model_validate(
                llm_client.chat_json(
                    system_prompt=_system_prompt(),
                    user_prompt=_user_prompt(
                        prompt=req.prompt,
                        prompt_signals=prompt_signals,
                        vertical_norm=vertical_norm,
                        expected_domain=expected_domain,
                        observed_domain=observed_domain,
                        notes=req.notes,
                    ),
                    response_format=True,
                    retry_invalid_schema=True,
                    validator=_is_valid_llm_payload,
                    max_tokens=900,
                )
            )
        except ForgeError:
            suggestion = _build_fallback_suggestion(
                prompt=req.prompt,
                prompt_signals=prompt_signals,
                expected_domain=expected_domain,
                observed_domain=observed_domain,
            )
            suggestion_source_type = "trace_review"
        except LLM_SUGGESTION_FALLBACK_ERRORS as exc:
            del exc
            suggestion = _build_fallback_suggestion(
                prompt=req.prompt,
                prompt_signals=prompt_signals,
                expected_domain=expected_domain,
                observed_domain=observed_domain,
            )
            suggestion_source_type = "trace_review"

        candidate_key = _normalize_candidate_key(
            req.candidate_key
            or suggestion.candidate_key
            or _default_candidate_key(
                prompt_signals=prompt_signals,
                expected_domain_name=str(expected_domain.get("domain_name") or ""),
            )
        )
        if not candidate_key:
            raise ForgeError("AI suggestion did not produce a usable candidate_key", status_code=500)

        rationale = dict(suggestion.rationale or {})
        rationale.setdefault("observed_failure_prompt", req.prompt)
        rationale.setdefault("prompt_signals", prompt_signals)
        rationale.setdefault("expected_domain", _compact_domain_snapshot(expected_domain))
        if observed_domain is not None:
            rationale.setdefault("observed_domain", _compact_domain_snapshot(observed_domain))
            rationale.setdefault(
                "missing_capabilities_on_observed",
                sorted(set(expected_domain["present_capabilities"]) - set(observed_domain["present_capabilities"])),
            )
            rationale.setdefault(
                "present_capabilities_on_expected",
                list(expected_domain["present_capabilities"]),
            )
        if req.notes:
            rationale.setdefault("notes", req.notes)
        rationale.setdefault("generation_mode", "ai" if suggestion_source_type == "ai_recommendation" else "fallback_heuristic")

        candidate = self._candidates.create_candidate(
            workspace_id=workspace_id,
            payload={
                "candidate_key": candidate_key,
                "source_type": suggestion_source_type,
                "workspace_id": workspace_id,
                "candidate_policy": suggestion.candidate_policy.model_dump(),
                "rationale_json": rationale,
                "confidence": suggestion.confidence,
            },
        )
        return {
            "candidate": candidate,
            "prompt_signals": prompt_signals,
            "expected_domain": _compact_domain_snapshot(expected_domain),
            "observed_domain": _compact_domain_snapshot(observed_domain) if observed_domain is not None else None,
            "llm_resolution": llm_resolution,
            "generation_mode": "ai" if suggestion_source_type == "ai_recommendation" else "fallback_heuristic",
        }

    def _build_domain_snapshot(
        self,
        *,
        workspace_id: str,
        user_id: str,
        domain_id: int,
        vertical_norm: str,
    ) -> Dict[str, Any]:
        domain_name = self._load_domain_name(workspace_id=workspace_id, domain_id=domain_id)
        capabilities = self._domain_capabilities.get_domain_capabilities(
            workspace_id=workspace_id,
            user_id=user_id,
            domain_id=domain_id,
            vertical_norm=vertical_norm,
        )
        dimensions = list(capabilities.get("dimensions") or [])
        resolved = self._planner_capabilities.resolve_capabilities(
            workspace_id=workspace_id,
            vertical_norm=vertical_norm,
            base_domain_id=domain_id,
            capabilities=capabilities,
            shortlisted_columns=dimensions,
        )
        return {
            "base_domain_id": int(domain_id),
            "domain_name": domain_name,
            "present_capabilities": list(resolved.get("present") or []),
            "capability_records": list(resolved.get("records") or []),
            "metric_keys": sorted(
                {
                    str(item.get("metric_key") or "").strip()
                    for item in list(capabilities.get("domain_metrics") or [])
                    if str(item.get("metric_key") or "").strip()
                }
            ),
            "dimension_keys": [
                str(item.get("column_key") or "").strip()
                for item in dimensions[:20]
                if str(item.get("column_key") or "").strip()
            ],
        }

    def _load_domain_name(self, *, workspace_id: str, domain_id: int) -> str:
        rows = self._sql.execute_query_mappings(
            """
            SELECT name
            FROM domain
            WHERE workspace_id = :workspace_id
              AND id = :domain_id
            LIMIT 1
            """,
            {"workspace_id": str(workspace_id), "domain_id": int(domain_id)},
        )
        if not rows:
            raise ForgeError("Domain not found", status_code=404)
        return str(rows[0].get("name") or "").strip() or f"Domain {domain_id}"

    def _resolve_llm(
        self,
        *,
        workspace_id: str,
        llm_id: Optional[int],
    ) -> tuple[LLMClient, Dict[str, Any]]:
        if self._explicit_llm is not None:
            return (
                self._explicit_llm,
                {
                    "source": "explicit",
                    "role": LLMRole.PLANNER,
                    "workspace_id": workspace_id,
                    "llm_id": llm_id,
                },
            )
        resolved = self._llm_runtime_builder(
            workspace_id=workspace_id,
            role=LLMRole.PLANNER,
            llm_id_override=llm_id,
        )
        return (
            resolved.client,
            {
                "source": resolved.source,
                "role": resolved.role,
                "workspace_id": resolved.workspace_id,
                "llm_id": resolved.llm_id,
                "provider": resolved.provider,
                "model": resolved.model,
                "endpoint": resolved.endpoint,
            },
        )


def _is_valid_llm_payload(payload: Dict[str, Any]) -> bool:
    try:
        PlannerRerankPolicyCandidateSuggestionLLMResponse.model_validate(payload)
    except LLM_SUGGESTION_VALIDATION_ERRORS:
        return False
    return True


def _system_prompt() -> str:
    return (
        "You generate typed planner rerank policy candidates for QueryForge.\n"
        "Return JSON only.\n"
        "Do not activate a production policy.\n"
        "Choose only from the provided known signals and known capabilities.\n"
        "Prefer capability-based rules that explain why the expected domain should outrank the observed domain.\n"
        "Keep the rule narrow, deterministic, and bounded.\n"
        "Use the response shape:\n"
        "{\n"
        '  "candidate_key": "string",\n'
        '  "confidence": 0.0,\n'
        '  "candidate_policy": { ...typed rule... },\n'
        '  "rationale": { ...object... }\n'
        "}\n"
    )


def _user_prompt(
    *,
    prompt: str,
    prompt_signals: List[str],
    vertical_norm: str,
    expected_domain: Mapping[str, Any],
    observed_domain: Optional[Mapping[str, Any]],
    notes: Optional[str],
) -> str:
    context = {
        "task": "Suggest one pending planner rerank policy candidate.",
        "vertical_norm": vertical_norm,
        "prompt": prompt,
        "prompt_signals": prompt_signals,
        "known_signals": sorted(PLANNER_RERANK_SIGNAL_KEYS),
        "known_capabilities": sorted(PLANNER_RERANK_CAPABILITY_KEYS),
        "expected_domain": _compact_domain_snapshot(expected_domain),
        "observed_domain": _compact_domain_snapshot(observed_domain) if observed_domain is not None else None,
        "notes": notes or None,
        "requirements": [
            "candidate_policy must validate against the typed production rule contract",
            "at least one signal matcher is required",
            "prefer capability-based boosts and penalties over prompt hacks",
            "use max_effect no larger than 0.35 unless clearly justified",
            "if observed_domain is present, explain the capability gap in rationale",
        ],
    }
    return json.dumps(context, indent=2, sort_keys=True)


def _default_candidate_key(*, prompt_signals: List[str], expected_domain_name: str) -> str:
    signal_tokens = [_slugify(token) for token in prompt_signals[:4] if _slugify(token)]
    domain_token = _slugify(expected_domain_name)[:40]
    pieces = ["ai"]
    if signal_tokens:
        pieces.extend(signal_tokens[:3])
    if domain_token:
        pieces.append(domain_token)
    pieces.append("policy")
    return "_".join(piece for piece in pieces if piece)[:150]


def _normalize_candidate_key(value: Optional[str]) -> str:
    token = _slugify(value or "")
    if not token:
        return ""
    if not token[0].isalpha():
        token = f"policy_{token}"
    return token[:150]


def _slugify(value: str) -> str:
    token = _SLUG_RE.sub("_", str(value or "").strip().lower()).strip("_")
    return re.sub(r"_+", "_", token)


def _compact_domain_snapshot(domain: Optional[Mapping[str, Any]]) -> Optional[Dict[str, Any]]:
    if domain is None:
        return None
    return {
        "base_domain_id": int(domain.get("base_domain_id") or 0),
        "domain_name": str(domain.get("domain_name") or ""),
        "present_capabilities": list(domain.get("present_capabilities") or []),
        "metric_keys": list(domain.get("metric_keys") or []),
        "dimension_keys": list(domain.get("dimension_keys") or []),
    }


def _build_fallback_suggestion(
    *,
    prompt: str,
    prompt_signals: List[str],
    expected_domain: Mapping[str, Any],
    observed_domain: Optional[Mapping[str, Any]],
) -> PlannerRerankPolicyCandidateSuggestionLLMResponse:
    present = [str(item).strip().upper() for item in list(expected_domain.get("present_capabilities") or []) if str(item).strip()]
    observed_present = {
        str(item).strip().upper()
        for item in list((observed_domain or {}).get("present_capabilities") or [])
        if str(item).strip()
    }
    signal_list = _fallback_signal_list(prompt_signals)
    prefer = _fallback_prefer_capabilities(prompt_signals=signal_list, expected_present=present)
    if not prefer:
        raise ForgeError(
            "AI helper could not derive a capability-grounded suggestion for this prompt. Try a prompt with clearer planner constraints or provide an observed wrong domain for contrast.",
            status_code=422,
            details={
                "prompt_signals": signal_list,
                "expected_domain": _compact_domain_snapshot(expected_domain),
                "observed_domain": _compact_domain_snapshot(observed_domain),
            },
        )
    penalize_missing = [cap for cap in prefer if cap not in observed_present] if observed_domain is not None else []
    require_for_bonus = [
        cap
        for cap in prefer
        if cap in {"STUDENT_IDENTITY", "SCHOOL_NAME", "ENROLLMENT_STATUS", "STAFF_IDENTITY", "BIRTH_DATE", "AGE"}
    ]
    boost = 0.2 if prefer else 0.1
    penalty = 0.2 if penalize_missing else 0.0
    max_effect = 0.3 if penalize_missing else 0.2
    if not require_for_bonus and prefer:
        require_for_bonus = prefer[:1]

    return PlannerRerankPolicyCandidateSuggestionLLMResponse(
        candidate_key=_default_candidate_key(
            prompt_signals=signal_list,
            expected_domain_name=str(expected_domain.get("domain_name") or ""),
        ),
        confidence=0.55,
        candidate_policy=PlannerRerankPolicyRule(
            version=1,
            when_signals_all=signal_list,
            when_signals_any=[],
            exclude_signals_any=[],
            prefer_capabilities=prefer,
            penalize_missing=penalize_missing,
            require_for_bonus=require_for_bonus,
            boost=boost,
            penalty=penalty,
            max_effect=max_effect,
        ),
        rationale={
            "fallback_reason": "llm_response_invalid_or_unavailable",
            "observed_failure_prompt": prompt,
            "expected_domain": _compact_domain_snapshot(expected_domain),
            "observed_domain": _compact_domain_snapshot(observed_domain),
        },
    )


def _fallback_signal_list(prompt_signals: List[str]) -> List[str]:
    ordered = [signal for signal in prompt_signals if signal in PLANNER_RERANK_SIGNAL_KEYS]
    if ordered:
        return ordered[: min(3, len(ordered))]
    return ["time_constraint_present"]


def _fallback_prefer_capabilities(*, prompt_signals: List[str], expected_present: List[str]) -> List[str]:
    preferred: List[str] = []
    mapping = {
        "student_listing": ["STUDENT_IDENTITY"],
        "student_aggregate": ["STUDENT_COUNT"],
        "age_extreme_prompt": ["BIRTH_DATE", "AGE", "STUDENT_IDENTITY"],
        "birth_month_prompt": ["BIRTH_DATE", "STUDENT_IDENTITY"],
        "staff_listing": ["STAFF_IDENTITY"],
        "staff_role_prompt": ["STAFF_ROLE"],
        "calendar_days_off_prompt": ["CALENDAR_DATE", "SCHOOL_DAY_FLAG", "NON_INSTRUCTIONAL_DAY"],
        "school_literal_present": ["SCHOOL_NAME", "SCHOOL_IDENTITY"],
        "district_literal_present": ["DISTRICT_NAME"],
        "status_enrolled": ["ENROLLMENT_STATUS"],
        "needs_school_filter": ["SCHOOL_NAME"],
        "needs_enrollment_status": ["ENROLLMENT_STATUS"],
        "subgroup_prompt": ["RACE_ETHNICITY", "GENDER"],
        "program_prompt": ["PROGRAM_MEMBERSHIP"],
        "needs_attendance_metric": ["ATTENDANCE_RATE"],
        "needs_grade_metric": ["COURSE_GRADE"],
        "time_constraint_present": [],
    }
    expected_set = set(expected_present)
    for signal in prompt_signals:
        for capability in mapping.get(signal, []):
            if capability in expected_set and capability not in preferred:
                preferred.append(capability)
    return preferred[:3]


__all__ = ["PlannerRerankPolicyCandidateSuggestionService"]
