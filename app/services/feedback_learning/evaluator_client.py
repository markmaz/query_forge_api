from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional

from pydantic import ValidationError

from app.config.feedback_learning_config import FEEDBACK_EVALUATOR_MAX_RETRIES
from app.exceptions.forge_error import ForgeError
from app.schemas.feedback_learning import EvaluatorAnalysis, PromptArtifactBundle
from app.services.feedback_learning.evaluator_prompt_builder import EvaluatorPromptBuilder
from app.services.llm.llm_client import LLMClient


@dataclass(frozen=True)
class EvaluatorClientResult:
    analysis: EvaluatorAnalysis
    raw_output: str
    attempts: int
    model: Optional[str] = None
    trace: Optional[Dict[str, Any]] = None


class EvaluatorClient:
    def __init__(
        self,
        *,
        llm_client: Optional[LLMClient] = None,
        prompt_builder: Optional[EvaluatorPromptBuilder] = None,
        max_retries: Optional[int] = None,
    ) -> None:
        self._llm_client = llm_client or LLMClient()
        self._prompt_builder = prompt_builder or EvaluatorPromptBuilder()
        self._max_retries = max(0, int(FEEDBACK_EVALUATOR_MAX_RETRIES if max_retries is None else max_retries))

    def analyze_failure(self, bundle: PromptArtifactBundle) -> EvaluatorAnalysis:
        return self.analyze_failure_with_trace(bundle).analysis

    def analyze_failure_with_trace(self, bundle: PromptArtifactBundle) -> EvaluatorClientResult:
        prompts = self._prompt_builder.build_prompts(bundle=bundle)
        system_prompt = prompts["system_prompt"]
        user_prompt = prompts["user_prompt"]

        raw_output = ""
        attempts = 0
        errors: List[Dict[str, Any]] = []
        final_trace: Optional[Dict[str, Any]] = None

        for attempt_index in range(self._max_retries + 1):
            attempts = attempt_index + 1
            prompt = user_prompt if attempt_index == 0 else self._repair_prompt(previous_output=raw_output)
            trace = self._llm_client.chat_json_with_trace(
                system_prompt=system_prompt,
                user_prompt=prompt,
                response_format={"type": "json_object"},
            )
            final_trace = dict(trace or {}) if isinstance(trace, Mapping) else None
            raw_output = str(trace.get("content") or trace.get("raw_text") or "").strip()
            parsed = trace.get("parsed") if isinstance(trace.get("parsed"), dict) else None
            if parsed is None:
                errors.append({"attempt": attempts, "error": "missing_json_object"})
                continue
            try:
                analysis = EvaluatorAnalysis.model_validate(parsed)
            except ValidationError as exc:
                errors.append({"attempt": attempts, "error": "invalid_schema", "details": exc.errors()})
                continue
            return EvaluatorClientResult(
                analysis=analysis,
                raw_output=raw_output,
                attempts=attempts,
                model=getattr(self._llm_client, "_model", None),
                trace=final_trace,
            )

        raise ForgeError(
            "Evaluator returned invalid analysis payload",
            status_code=502,
            details={
                "attempts": attempts,
                "raw_output": raw_output,
                "errors": errors,
            },
        )

    def _repair_prompt(self, *, previous_output: str) -> str:
        excerpt = str(previous_output or "").strip()[:3000]
        return (
            "Your previous response did not match the required JSON schema.\n"
            "Return JSON only, with no prose, markdown, or code fences.\n"
            f"Previous output:\n{excerpt}"
        )


__all__ = ["EvaluatorClient", "EvaluatorClientResult"]
