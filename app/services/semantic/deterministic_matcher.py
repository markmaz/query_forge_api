from __future__ import annotations

import re
from typing import Dict, List

_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "by",
    "for",
    "from",
    "in",
    "is",
    "me",
    "of",
    "on",
    "or",
    "show",
    "the",
    "to",
    "with",
}

_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")


class DeterministicMatcher:
    def match(self, prompt: str) -> Dict[str, List[Dict[str, object]] | List[str]]:
        text = str(prompt or "").strip()
        lowered = text.lower()
        tokens = [tok for tok in _TOKEN_RE.findall(lowered)]

        matched: List[Dict[str, object]] = []
        matched_tokens = set()

        if "school year" in lowered:
            matched.append(
                {
                    "token": "school year",
                    "concept_key": "SCHOOL_YEAR",
                    "confidence": 0.95,
                    "reason": "obvious time field heuristic",
                }
            )
            matched_tokens.update({"school", "year"})
        if "calendar year" in lowered:
            matched.append(
                {
                    "token": "calendar year",
                    "concept_key": "CALENDAR_YEAR",
                    "confidence": 0.92,
                    "reason": "obvious time field heuristic",
                }
            )
            matched_tokens.update({"calendar", "year"})

        for token in tokens:
            if token in matched_tokens:
                continue
            candidate = _match_token(token)
            if candidate is None:
                continue
            matched.append(candidate)
            matched_tokens.add(token)

        unmatched_tokens = [tok for tok in tokens if tok not in matched_tokens and tok not in _STOPWORDS]

        return {
            "matched": matched,
            "unmatched_tokens": unmatched_tokens,
        }


def _match_token(token: str) -> Dict[str, object] | None:
    if token.startswith("k_"):
        suffix = token[2:].strip("_")
        if suffix == "":
            return None
        if "lea" in suffix:
            concept_key = "LEA_ID"
        elif "school" in suffix:
            concept_key = "SCHOOL_ID"
        elif "student" in suffix:
            concept_key = "STUDENT_ID"
        else:
            concept_key = f"{suffix.upper()}_ID"
        return {
            "token": token,
            "concept_key": concept_key,
            "confidence": 0.95,
            "reason": "k_* identifier heuristic",
        }

    if token.endswith("_id") or token == "id":
        return {
            "token": token,
            "concept_key": token.upper(),
            "confidence": 0.9,
            "reason": "identifier suffix heuristic",
        }

    if token in {"date", "enroll_date", "birth_date"} or token.endswith("_date"):
        return {
            "token": token,
            "concept_key": "DATE",
            "confidence": 0.88,
            "reason": "obvious time field heuristic",
        }

    if token in {"year", "school_year", "calendar_year"}:
        return {
            "token": token,
            "concept_key": token.upper(),
            "confidence": 0.9,
            "reason": "obvious time field heuristic",
        }

    if token in {"tenant_code", "namespace"} or "tenant" in token:
        return {
            "token": token,
            "concept_key": "TENANT_CODE",
            "confidence": 0.8,
            "reason": "tenant/category heuristic",
        }

    return None


__all__ = ["DeterministicMatcher"]
