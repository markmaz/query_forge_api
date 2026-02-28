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
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z'\-]*")


class DeterministicMatcher:
    def match(self, prompt: str) -> Dict[str, List[Dict[str, object]] | List[str]]:
        text = str(prompt or "").strip()
        lowered = text.lower()
        tokens = [tok for tok in _TOKEN_RE.findall(lowered)]
        extracted_values = _extract_name_values(text) + _extract_school_values(text)

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

        out: Dict[str, List[Dict[str, object]] | List[str]] = {
            "matched": matched,
            "unmatched_tokens": unmatched_tokens,
        }
        if extracted_values:
            out["extracted_values"] = extracted_values
        return out


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


def _extract_name_values(prompt: str) -> List[Dict[str, object]]:
    text = str(prompt or "").strip()
    if text == "":
        return []

    found: List[Dict[str, object]] = []
    seen: set[str] = set()
    pattern = re.compile(r"\b(named|name\s+is|called)\b", flags=re.IGNORECASE)

    for match in pattern.finditer(text):
        keyword = _normalize_name_keyword(match.group(1))
        tail = text[match.end() :].lstrip()
        if tail == "":
            continue

        quoted = re.match(r"^([\"'])(.+?)\1", tail)
        if quoted:
            quoted_value = _extract_quoted_name(quoted.group(2))
            if quoted_value:
                _append_name_extraction(found, seen, quoted_value, f"pattern:{keyword}")
            continue

        value = _extract_next_name_token(tail)
        if value:
            _append_name_extraction(found, seen, value, f"pattern:{keyword}")
    return found


def _normalize_name_keyword(raw: str) -> str:
    text = str(raw or "").strip().lower()
    if text.startswith("name is"):
        return "name is"
    if text.startswith("called"):
        return "called"
    return "named"


def _extract_quoted_name(value: str) -> str:
    tokens = [tok for tok in _WORD_RE.findall(str(value or "").strip()) if tok]
    if not tokens:
        return ""
    return " ".join(tokens[:3]).strip()


def _extract_next_name_token(text: str) -> str:
    for token in _WORD_RE.findall(str(text or "")):
        lowered = token.lower()
        if lowered in _STOPWORDS:
            continue
        return token.strip(".,;:!?()[]{}\"'")
    return ""


def _append_name_extraction(
    out: List[Dict[str, object]],
    seen: set[str],
    value: str,
    source: str,
) -> None:
    _append_extraction(
        out=out,
        seen=seen,
        kind="name",
        value=value,
        source=source,
    )


def _extract_school_values(prompt: str) -> List[Dict[str, object]]:
    text = str(prompt or "").strip()
    if text == "":
        return []

    found: List[Dict[str, object]] = []
    seen: set[str] = set()

    quoted_pattern = re.compile(r"\bat\s+[\"']([^\"']+)[\"']", flags=re.IGNORECASE)
    for match in quoted_pattern.finditer(text):
        value = _normalize_school_value(match.group(1))
        if value:
            _append_extraction(
                out=found,
                seen=seen,
                kind="school_name",
                value=value,
                source="pattern:at_school",
            )

    school_pattern = re.compile(
        r"\bat\s+the\s+([A-Za-z0-9][A-Za-z0-9'&\-\s]{0,120}?)\s+"
        r"(elementary school|middle school|high school|school)\b",
        flags=re.IGNORECASE,
    )
    for match in school_pattern.finditer(text):
        phrase = f"{match.group(1)} {match.group(2)}"
        value = _normalize_school_value(phrase)
        if value:
            _append_extraction(
                out=found,
                seen=seen,
                kind="school_name",
                value=value,
                source="pattern:at_school",
            )
    return found


def _normalize_school_value(value: str) -> str:
    text = str(value or "").strip()
    text = text.strip(".,;:!?()[]{}\"'")
    text = re.sub(r"\s+", " ", text)
    return text


def _append_extraction(
    out: List[Dict[str, object]],
    seen: set[str],
    kind: str,
    value: str,
    source: str,
) -> None:
    normalized = str(value or "").strip()
    if normalized == "":
        return
    key = f"{kind}:{normalized.lower()}"
    if key in seen:
        return
    seen.add(key)
    out.append({"kind": kind, "value": normalized, "source": source})


__all__ = ["DeterministicMatcher"]
