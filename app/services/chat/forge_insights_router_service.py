from __future__ import annotations

import re
from typing import Any, Dict, List, Mapping, Optional

from pydantic import ValidationError

from app.config import (
    QF_FORGE_INSIGHTS_AUTO_PLAN_ENABLED,
    QF_FORGE_INSIGHTS_ROUTE_CONFIDENCE_THRESHOLD,
    QF_FORGE_INSIGHTS_ROUTE_DOMAIN_VECTOR_ENABLED,
    QF_FORGE_INSIGHTS_ROUTE_DOMAIN_VECTOR_LIMIT,
    QF_FORGE_INSIGHTS_ROUTE_DOMAIN_VECTOR_SCORE_THRESHOLD,
    QF_FORGE_INSIGHTS_ROUTE_LLM_MAX_TOKENS,
)
from app.exceptions.forge_error import ForgeError
from app.services.chat.education_fewshot_service import EducationFewshotService
from app.services.chat.minimal_chat_service import ForgeInsightsChatService, MinimalChatRequest
from app.services.execution_service import ExecutionService
from app.services.llm.llm_client import LLMClient
from app.services.planner_domain import PlannerDomainService
from app.services.vector import DomainVectorIndexService

_EDU_KEYWORD_RE = re.compile(
    r"\b(student|students|school|schools|district|districts|education|lea|teacher|teachers|principal|principals|enrollment|attendance|staff|grade|grades|classroom|campus|kid|kids|score|scores|esl|homeless|demographic|demographics|ethnicity|discipline)\b",
    re.IGNORECASE,
)
_ANALYTICS_HINT_RE = re.compile(
    r"\b(show|list|find|count|how many|average|avg|top|bottom|sort|filter|group by|breakdown|trend|compare)\b",
    re.IGNORECASE,
)
_STUDENT_TERM_RE = re.compile(r"\bstudent(s)?\b", re.IGNORECASE)
_STAFF_TERM_RE = re.compile(
    r"\b(staff|teacher|teachers|principal|principals|counselor|counselors|administrator|administrators)\b",
    re.IGNORECASE,
)
_SCHOOL_CONTEXT_RE = re.compile(
    r"\b(school|schools|elementary|middle|high|academy|campus|district|districts|enrolled|enrollment|attend|attendance)\b",
    re.IGNORECASE,
)
_FORCE_EDU_KEYWORD_RE = re.compile(
    r"\b(school|schools|district|districts|education|lea|student|students|kid|kids|score|scores|grades?|grade level|esl|homeless|demographic|demographics|ethnicity|attendance|discipline)\b",
    re.IGNORECASE,
)
_ROUTE_SYSTEM_PROMPT = (
    "Classify whether the user prompt should run through an education analytics SQL planning pipeline. "
    "If the prompt includes education indicators like school, district, education, lea, student, kid, scores, grades, ESL, homeless, demographics, ethnicity, attendance, or discipline, choose education_pipeline. "
    "Return JSON only with keys: route, confidence, reason. "
    "route must be one of: education_pipeline, chat."
)
_MAX_INBOUND_MESSAGES = 30


class ForgeInsightsRouterService:
    def __init__(
        self,
        *,
        chat_service: Optional[ForgeInsightsChatService] = None,
        planner_domain_service: Optional[PlannerDomainService] = None,
        execution_service: Optional[ExecutionService] = None,
        llm_client: Optional[LLMClient] = None,
        fewshot_service: Optional[EducationFewshotService] = None,
        domain_vector_service: Optional[DomainVectorIndexService] = None,
        auto_plan_enabled: bool = QF_FORGE_INSIGHTS_AUTO_PLAN_ENABLED,
        route_confidence_threshold: float = QF_FORGE_INSIGHTS_ROUTE_CONFIDENCE_THRESHOLD,
        route_llm_max_tokens: int = QF_FORGE_INSIGHTS_ROUTE_LLM_MAX_TOKENS,
        route_domain_vector_enabled: bool = QF_FORGE_INSIGHTS_ROUTE_DOMAIN_VECTOR_ENABLED,
        route_domain_vector_limit: int = QF_FORGE_INSIGHTS_ROUTE_DOMAIN_VECTOR_LIMIT,
        route_domain_vector_score_threshold: float = QF_FORGE_INSIGHTS_ROUTE_DOMAIN_VECTOR_SCORE_THRESHOLD,
    ) -> None:
        self._chat = chat_service or ForgeInsightsChatService()
        self._planner = planner_domain_service or PlannerDomainService()
        self._execution = execution_service or ExecutionService()
        self._llm = llm_client or LLMClient()
        self._fewshots = fewshot_service or EducationFewshotService()
        self._domain_vector = domain_vector_service or getattr(self._planner, "_domain_vector", None)
        self._auto_plan_enabled = bool(auto_plan_enabled)
        self._route_confidence_threshold = max(0.0, min(float(route_confidence_threshold), 1.0))
        self._route_llm_max_tokens = max(40, int(route_llm_max_tokens))
        self._route_domain_vector_enabled = bool(route_domain_vector_enabled)
        self._route_domain_vector_limit = max(1, min(int(route_domain_vector_limit), 5))
        self._route_domain_vector_score_threshold = max(0.0, min(float(route_domain_vector_score_threshold), 1.0))

    def ask(
        self,
        body: Mapping[str, Any],
        *,
        workspace_id: str,
        user_id: str,
        query_args: Optional[Mapping[str, Any]] = None,
    ) -> tuple[Dict[str, Any], int]:
        payload, inbound_messages_truncated = _normalize_inbound_payload(dict(body or {}))
        try:
            req = MinimalChatRequest.model_validate(payload)
        except ValidationError as exc:
            raise ForgeError(
                "Invalid chat request",
                status_code=400,
                details={"errors": _safe_validation_errors(exc)},
            ) from exc

        user_prompt = _latest_user_message(payload)
        if user_prompt is None:
            raise ForgeError("messages must include at least one user message", status_code=400)

        decision = self._route_decision(prompt=user_prompt, workspace_id=workspace_id, user_id=user_id)
        if inbound_messages_truncated:
            decision = dict(decision)
            decision["inbound_messages_truncated"] = True
        if self._auto_plan_enabled and decision.get("route") == "education_pipeline":
            plan_payload: Dict[str, Any] = {
                "workspace_id": workspace_id,
                "prompt": user_prompt,
                "vertical_norm": "education",
                "debug": bool(req.debug),
                # Allow fi_* conversations to bootstrap the planner store on first request.
                "allow_unknown_conversation": True,
            }
            if req.conversation_id:
                plan_payload["conversation_id"] = req.conversation_id

            plan_result = self._planner.plan(plan_payload, user_id=user_id)
            sql_json = plan_result.get("sql_json")
            if not isinstance(sql_json, dict) or not sql_json:
                raise ForgeError(
                    "planner did not produce executable sql_json",
                    status_code=422,
                    details={"validation": plan_result.get("validation")},
                )

            exec_payload: Dict[str, Any] = {"sqlJson": sql_json, "kind": "query_builder"}
            if payload.get("limit") is not None:
                exec_payload["limit"] = payload.get("limit")
            if payload.get("offset") is not None:
                exec_payload["offset"] = payload.get("offset")
            exec_result, exec_status = self._execution.start(workspace_id, exec_payload, dict(query_args or {}))

            summary = _plan_summary(plan_result)
            return {
                "mode": "education_pipeline",
                "route": "plan_domain",
                "conversation_id": plan_result.get("conversation_id") or req.conversation_id,
                "trace_id": plan_result.get("trace_id"),
                "message": {"role": "assistant", "content": summary},
                "plan_result": plan_result,
                "execution": exec_result,
                "execution_status_code": exec_status,
                "route_decision": decision,
            }, 200

        out = self._chat.chat(payload, workspace_id=workspace_id, user_id=user_id)
        out["mode"] = "chat"
        out["route"] = "chat"
        if req.debug:
            debug = dict(out.get("debug") or {})
            debug["route_decision"] = decision
            out["debug"] = debug
        return out, 200

    def _route_decision(self, *, prompt: str, workspace_id: str, user_id: str) -> Dict[str, Any]:
        fewshot_examples = self._fewshots.get_examples(workspace_id=workspace_id, user_id=user_id)
        keyword_force_match = _force_education_keyword_match(prompt)
        heuristic_score = _heuristic_education_score(prompt)
        hard_match = _hard_education_match(prompt)
        vector_hit = self._domain_vector_hit(prompt=prompt, workspace_id=workspace_id)
        if vector_hit.get("matched") is True:
            return {
                "route": "education_pipeline",
                "confidence": 0.95,
                "reason": "domain vector precheck matched education domain",
                "method": "domain_vector",
                "heuristic_score": heuristic_score,
                "hard_match": hard_match,
                "keyword_force_match": keyword_force_match,
                "fewshot_count": len(fewshot_examples),
                "domain_vector_match": vector_hit,
            }
        fallback_route = "education_pipeline" if (hard_match or heuristic_score >= 0.7) else "chat"
        fallback = {
            "route": fallback_route,
            "confidence": max(heuristic_score, 0.92 if hard_match else heuristic_score),
            "reason": "hard education rule" if hard_match else "heuristic fallback",
            "method": "heuristic",
            "heuristic_score": heuristic_score,
            "hard_match": hard_match,
            "keyword_force_match": keyword_force_match,
            "fewshot_count": len(fewshot_examples),
            "domain_vector_match": vector_hit,
        }

        try:
            llm_out = self._llm.chat_json(
                system_prompt=_ROUTE_SYSTEM_PROMPT,
                user_prompt=_build_route_user_prompt(prompt=prompt, fewshot_examples=fewshot_examples),
                response_format=True,
                max_tokens=self._route_llm_max_tokens,
                validator=lambda body: isinstance(body.get("route"), str) and body.get("route") in {"education_pipeline", "chat"},
            )
        except Exception:
            return fallback

        route = str(llm_out.get("route") or "").strip().lower()
        if route not in {"education_pipeline", "chat"}:
            return fallback
        try:
            confidence = float(llm_out.get("confidence"))
        except Exception:
            confidence = 0.0
        confidence = max(0.0, min(confidence, 1.0))
        reason = str(llm_out.get("reason") or "").strip() or "llm route decision"
        method = "llm"

        if hard_match:
            route = "education_pipeline"
            confidence = max(confidence, 0.92)
            reason = f"{reason} (hard education rule)"
            method = "llm+rule"

        if route == "education_pipeline" and confidence < self._route_confidence_threshold and heuristic_score < 0.7:
            route = "chat"
            reason = f"{reason} (below confidence threshold)"

        return {
            "route": route,
            "confidence": confidence,
            "reason": reason,
            "method": method,
            "heuristic_score": heuristic_score,
            "hard_match": hard_match,
            "keyword_force_match": keyword_force_match,
            "fewshot_count": len(fewshot_examples),
            "domain_vector_match": vector_hit,
        }

    def _domain_vector_hit(self, *, prompt: str, workspace_id: str) -> Dict[str, Any]:
        if not self._route_domain_vector_enabled:
            return {"enabled": False, "matched": False}
        service = self._domain_vector
        if service is None:
            try:
                service = DomainVectorIndexService()
                self._domain_vector = service
            except Exception:
                return {"enabled": True, "matched": False, "error": "init_failed"}
        try:
            out = service.search_domains(
                workspace_id=workspace_id,
                query=prompt,
                vertical_norm="education",
                limit=self._route_domain_vector_limit,
                score_threshold=self._route_domain_vector_score_threshold,
                include_payload=False,
            )
        except Exception:
            return {"enabled": True, "matched": False, "error": "search_failed"}
        rows = out.get("results") if isinstance(out, Mapping) else []
        if not isinstance(rows, list):
            return {"enabled": True, "matched": False}
        best = rows[0] if rows else None
        if not isinstance(best, Mapping):
            return {"enabled": True, "matched": False, "count": 0}
        return {
            "enabled": True,
            "matched": True,
            "count": len(rows),
            "top_domain_id": int(best.get("domain_id") or 0),
            "top_score": float(best.get("score") or 0.0),
        }


def _latest_user_message(body: Mapping[str, Any]) -> Optional[str]:
    messages = body.get("messages")
    if not isinstance(messages, list):
        return None
    for item in reversed(messages):
        if not isinstance(item, Mapping):
            continue
        role = str(item.get("role") or "").strip().lower()
        if role != "user":
            continue
        text = str(item.get("content") or "").strip()
        if text:
            return text
    return None


def _heuristic_education_score(prompt: str) -> float:
    text = str(prompt or "").strip()
    if text == "":
        return 0.0
    score = 0.0
    edu_hits = len(_EDU_KEYWORD_RE.findall(text))
    if edu_hits > 0:
        score += min(0.8, 0.2 * edu_hits)
    if _ANALYTICS_HINT_RE.search(text):
        score += 0.25
    return max(0.0, min(score, 1.0))


def _hard_education_match(prompt: str) -> bool:
    text = str(prompt or "").strip()
    if text == "":
        return False
    if _force_education_keyword_match(text):
        return True
    has_school_context = bool(_SCHOOL_CONTEXT_RE.search(text))
    if not has_school_context:
        return False
    has_student_signal = bool(_STUDENT_TERM_RE.search(text))
    has_staff_signal = bool(_STAFF_TERM_RE.search(text))
    return has_student_signal or has_staff_signal


def _force_education_keyword_match(prompt: str) -> bool:
    text = str(prompt or "").strip()
    if text == "":
        return False
    return bool(_FORCE_EDU_KEYWORD_RE.search(text))


def _plan_summary(plan_result: Mapping[str, Any]) -> str:
    explanation = plan_result.get("explanation")
    if isinstance(explanation, Mapping):
        summary = explanation.get("summary")
        if isinstance(summary, str) and summary.strip():
            return summary.strip()
    return "I routed this request through the education pipeline and started the query execution."


def _build_route_user_prompt(*, prompt: str, fewshot_examples: list[str]) -> str:
    lines = [f"Prompt: {prompt}"]
    if fewshot_examples:
        lines.append("Examples that should route to education_pipeline:")
        for idx, example in enumerate(fewshot_examples, start=1):
            lines.append(f"{idx}. {example}")
    return "\n".join(lines)


def _normalize_inbound_payload(payload: Dict[str, Any]) -> tuple[Dict[str, Any], bool]:
    out = dict(payload or {})
    messages = out.get("messages")
    if not isinstance(messages, list):
        return out, False
    if len(messages) <= _MAX_INBOUND_MESSAGES:
        return out, False
    out["messages"] = messages[-_MAX_INBOUND_MESSAGES:]
    return out, True


def _safe_validation_errors(exc: ValidationError) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for row in exc.errors():
        if not isinstance(row, dict):
            rows.append({"message": str(row)})
            continue
        item = dict(row)
        if "ctx" in item and isinstance(item["ctx"], Mapping):
            item["ctx"] = {str(k): str(v) for k, v in item["ctx"].items()}
        rows.append(item)
    return rows


__all__ = ["ForgeInsightsRouterService"]
