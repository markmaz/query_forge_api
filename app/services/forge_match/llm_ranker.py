from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional, Sequence

from app.exceptions.forge_error import ForgeError
from app.services.forge_match.field_extractor import SourceFieldRecord
from app.services.llm.llm_client import LLMClient

logger = logging.getLogger(__name__)

_ALLOWED_DECISIONS = {"matched", "ambiguous", "no_confident_match"}
_ALLOWED_REASON_CODES = {
    "name_similarity",
    "description_similarity",
    "type_compatible",
    "domain_alignment",
    "table_alignment",
    "alias_alignment",
    "insufficient_signal",
    "ambiguous_candidates",
}


class ForgeMatchLLMRanker:
    def __init__(self, *, llm: Optional[LLMClient] = None, max_tokens: int = 500) -> None:
        self._llm = llm or LLMClient()
        self._max_tokens = max(200, int(max_tokens or 500))

    def rank(
        self,
        *,
        source_record: SourceFieldRecord,
        candidates: Sequence[Dict[str, Any]],
    ) -> Dict[str, Any]:
        if not candidates:
            return {
                "selected_column_id": None,
                "alternate_column_ids": [],
                "match_decision": "no_confident_match",
                "reason_codes": ["insufficient_signal"],
                "explanation": "No candidates were retrieved for this source field.",
                "ambiguity_note": "No candidates available.",
                "llm_confidence": 0.0,
            }

        candidate_ids = {int(row.get("column_id") or 0) for row in candidates if int(row.get("column_id") or 0) > 0}
        prompt = self._build_user_prompt(source_record=source_record, candidates=candidates)

        trace = self._llm.chat_json_with_trace(
            system_prompt=self._build_system_prompt(),
            user_prompt=prompt,
            response_format=True,
            max_tokens=self._max_tokens,
        )

        payload = _extract_json_payload(trace)
        if payload is None:
            repair_prompt = (
                "Your previous output was invalid. Return JSON only with keys: "
                "selected_column_id, alternate_column_ids, match_decision, reason_codes, explanation, ambiguity_note, llm_confidence.\n"
                f"Previous output: {str(trace.get('content') or trace.get('raw_text') or '')[:6000]}"
            )
            retry = self._llm.chat_json_with_trace(
                system_prompt=self._build_system_prompt(),
                user_prompt=repair_prompt,
                response_format=True,
                max_tokens=self._max_tokens,
            )
            payload = _extract_json_payload(retry)
            trace = retry

        if payload is None:
            logger.warning("ForgeMatch LLM rank response invalid JSON; falling back", extra={"trace": trace})
            return self._fallback_from_retrieval(candidates)

        normalized = _normalize_rank_payload(payload)
        if not _ids_are_valid(normalized, candidate_ids):
            logger.warning("ForgeMatch LLM rank returned out-of-set candidate IDs; forcing no_confident_match")
            normalized["selected_column_id"] = None
            normalized["alternate_column_ids"] = []
            normalized["match_decision"] = "no_confident_match"
            normalized["ambiguity_note"] = "Model selected candidates outside retrieved set; review required."
            normalized["reason_codes"] = ["insufficient_signal"]
            normalized["llm_confidence"] = min(float(normalized.get("llm_confidence") or 0.0), 0.25)
        return normalized

    @staticmethod
    def _build_system_prompt() -> str:
        return (
            "You rank retrieved column candidates for a mapping workflow.\n"
            "Return strict JSON only, no markdown.\n"
            "Never invent candidate IDs. You may only use candidate column_id values provided in input.\n"
            "If uncertain, return match_decision='ambiguous' or 'no_confident_match'."
        )

    @staticmethod
    def _build_user_prompt(*, source_record: SourceFieldRecord, candidates: Sequence[Dict[str, Any]]) -> str:
        compact_candidates = []
        for row in candidates:
            compact_candidates.append(
                {
                    "column_id": row.get("column_id"),
                    "column_name": row.get("column_name"),
                    "display_name": row.get("display_name"),
                    "table_name": row.get("table_name"),
                    "domain_name": row.get("domain_name"),
                    "description": row.get("description"),
                    "data_type": row.get("data_type"),
                    "vector_score": row.get("vector_score"),
                    "lexical_score": row.get("lexical_score"),
                    "combined_retrieval_score": row.get("combined_retrieval_score"),
                }
            )

        payload = {
            "source": {
                "row_id": source_record.row_id,
                "source_field_name": source_record.source_field_name,
                "source_description": source_record.source_description,
                "source_type": source_record.source_type,
                "source_object_name": source_record.source_object_name,
                "sample_value": source_record.sample_value,
            },
            "candidates": compact_candidates,
            "instructions": {
                "allowed_match_decisions": ["matched", "ambiguous", "no_confident_match"],
                "max_alternates": 2,
                "reason_code_allow_list": sorted(_ALLOWED_REASON_CODES),
            },
            "response_schema": {
                "selected_column_id": "integer|null",
                "alternate_column_ids": "array[integer] up to 2",
                "match_decision": "matched|ambiguous|no_confident_match",
                "reason_codes": "array[string]",
                "explanation": "string",
                "ambiguity_note": "string|null",
                "llm_confidence": "number 0..1",
            },
        }
        return json.dumps(payload, ensure_ascii=True)

    @staticmethod
    def _fallback_from_retrieval(candidates: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
        ranked = sorted(candidates, key=lambda row: float(row.get("combined_retrieval_score") or 0.0), reverse=True)
        if not ranked:
            return {
                "selected_column_id": None,
                "alternate_column_ids": [],
                "match_decision": "no_confident_match",
                "reason_codes": ["insufficient_signal"],
                "explanation": "No candidates available.",
                "ambiguity_note": "No candidates available.",
                "llm_confidence": 0.0,
            }

        top = ranked[0]
        top_id = int(top.get("column_id") or 0)
        score = float(top.get("combined_retrieval_score") or 0.0)
        if top_id > 0 and score >= 0.86:
            alternates = [int(row.get("column_id") or 0) for row in ranked[1:3] if int(row.get("column_id") or 0) > 0]
            return {
                "selected_column_id": top_id,
                "alternate_column_ids": alternates,
                "match_decision": "matched",
                "reason_codes": ["name_similarity", "description_similarity"],
                "explanation": "Top retrieved candidate selected by deterministic fallback.",
                "ambiguity_note": None,
                "llm_confidence": min(0.75, max(0.4, score)),
            }

        alternates = [int(row.get("column_id") or 0) for row in ranked[:2] if int(row.get("column_id") or 0) > 0]
        return {
            "selected_column_id": None,
            "alternate_column_ids": alternates,
            "match_decision": "ambiguous",
            "reason_codes": ["ambiguous_candidates"],
            "explanation": "Top candidates are close; manual review recommended.",
            "ambiguity_note": "Closest candidates have similar retrieval scores.",
            "llm_confidence": min(0.45, max(0.1, score)),
        }


def _extract_json_payload(trace: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    parsed = trace.get("parsed")
    if isinstance(parsed, dict):
        if "selected_column_id" in parsed:
            return parsed
        if isinstance(parsed.get("response"), dict):
            inner = parsed["response"]
            if "selected_column_id" in inner:
                return inner

    content = str(trace.get("content") or trace.get("raw_text") or "").strip()
    if content == "":
        return None
    try:
        payload = json.loads(content)
        if isinstance(payload, dict):
            return payload
    except Exception:
        pass

    # Best effort: extract first object.
    decoder = json.JSONDecoder()
    for idx, ch in enumerate(content):
        if ch != "{":
            continue
        try:
            obj, _ = decoder.raw_decode(content[idx:])
        except Exception:
            continue
        if isinstance(obj, dict):
            return obj
    return None


def _normalize_rank_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    decision = str(payload.get("match_decision") or "").strip().lower()
    if decision not in _ALLOWED_DECISIONS:
        decision = "no_confident_match"

    selected = payload.get("selected_column_id")
    try:
        selected_id = int(selected) if selected is not None else None
    except Exception:
        selected_id = None
    if selected_id is not None and selected_id <= 0:
        selected_id = None

    alternates: list[int] = []
    raw_alts = payload.get("alternate_column_ids")
    if isinstance(raw_alts, list):
        for item in raw_alts:
            try:
                parsed = int(item)
            except Exception:
                continue
            if parsed > 0 and parsed != selected_id and parsed not in alternates:
                alternates.append(parsed)
    alternates = alternates[:2]

    reason_codes: list[str] = []
    raw_reasons = payload.get("reason_codes")
    if isinstance(raw_reasons, list):
        for item in raw_reasons:
            text = str(item or "").strip().lower()
            if text and text in _ALLOWED_REASON_CODES and text not in reason_codes:
                reason_codes.append(text)

    explanation = str(payload.get("explanation") or "").strip()
    ambiguity_note = payload.get("ambiguity_note")
    if ambiguity_note is not None:
        ambiguity_note = str(ambiguity_note).strip() or None

    confidence_raw = payload.get("llm_confidence")
    try:
        llm_conf = float(confidence_raw)
    except Exception:
        llm_conf = 0.0
    llm_conf = max(0.0, min(1.0, llm_conf))

    return {
        "selected_column_id": selected_id,
        "alternate_column_ids": alternates,
        "match_decision": decision,
        "reason_codes": reason_codes,
        "explanation": explanation,
        "ambiguity_note": ambiguity_note,
        "llm_confidence": llm_conf,
    }


def _ids_are_valid(payload: Dict[str, Any], allowed: set[int]) -> bool:
    selected = payload.get("selected_column_id")
    if selected is not None and int(selected) not in allowed:
        return False
    for alt in payload.get("alternate_column_ids") or []:
        if int(alt) not in allowed:
            return False
    return True


__all__ = ["ForgeMatchLLMRanker"]
