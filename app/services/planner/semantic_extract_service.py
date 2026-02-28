from __future__ import annotations

from typing import Any, Callable, Dict, List

from app.nlp.extract import extract_entities


class SemanticExtractService:
    def __init__(self, *, extractor: Callable[[str], Dict[str, Any]] | None = None) -> None:
        self._extractor = extractor or extract_entities

    def extract_slots(self, prompt: str) -> Dict[str, List[str]]:
        payload = self._extractor(prompt)
        by_label = payload.get("by_label") if isinstance(payload, dict) else {}
        return {
            "metric": self._dedupe((by_label or {}).get("METRIC") or []),
            "dimensions": self._dedupe((by_label or {}).get("DIMENSION") or []),
            "subgroups": self._dedupe((by_label or {}).get("SUBGROUP") or []),
            "time_ranges": self._dedupe((by_label or {}).get("TIME_RANGE") or []),
            "org_schools": self._dedupe((by_label or {}).get("ORG_SCHOOL") or []),
            "org_districts": self._dedupe((by_label or {}).get("ORG_DISTRICT") or []),
        }

    def extract(self, prompt: str) -> Dict[str, Any]:
        payload = self._extractor(prompt)
        by_label = payload.get("by_label") if isinstance(payload, dict) else {}
        slots = {
            "metric": self._dedupe((by_label or {}).get("METRIC") or []),
            "dimensions": self._dedupe((by_label or {}).get("DIMENSION") or []),
            "subgroups": self._dedupe((by_label or {}).get("SUBGROUP") or []),
            "time_ranges": self._dedupe((by_label or {}).get("TIME_RANGE") or []),
            "org_schools": self._dedupe((by_label or {}).get("ORG_SCHOOL") or []),
            "org_districts": self._dedupe((by_label or {}).get("ORG_DISTRICT") or []),
        }
        return {
            "normalized_text": str((payload or {}).get("normalized_text") or "").strip(),
            "slots": slots,
            "ents": list((payload or {}).get("ents") or []),
            "by_label": dict(by_label or {}),
            "model": dict((payload or {}).get("model") or {}),
            "warnings": list((payload or {}).get("warnings") or []),
        }

    @staticmethod
    def _dedupe(values: List[Any]) -> List[str]:
        out: List[str] = []
        seen = set()
        for raw in list(values or []):
            value = str(raw or "").strip()
            if value == "":
                continue
            key = value.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(value)
        return out
