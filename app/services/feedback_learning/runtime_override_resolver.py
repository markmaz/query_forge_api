from __future__ import annotations

import re
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from app.config.feedback_learning_config import FEEDBACK_WORKSPACE_OVERRIDES_ENABLED
from app.repositories.feedback_learning import DomainOverrideRepository, SemanticOverrideRepository


_PROMPT_TOKEN_RE = re.compile(r"[^a-z0-9\s]+")


class RuntimeOverrideResolver:
    def __init__(
        self,
        *,
        semantic_override_repository: Optional[SemanticOverrideRepository] = None,
        domain_override_repository: Optional[DomainOverrideRepository] = None,
        enabled: Optional[bool] = None,
    ) -> None:
        self._semantic_override_repository = (
            semantic_override_repository or SemanticOverrideRepository()
        )
        self._domain_override_repository = (
            domain_override_repository or DomainOverrideRepository()
        )
        self._enabled = (
            FEEDBACK_WORKSPACE_OVERRIDES_ENABLED if enabled is None else bool(enabled)
        )

    def resolve_alias_rows(
        self,
        *,
        base_rows: Sequence[Mapping[str, Any]],
        workspace_id: Optional[str],
    ) -> List[Dict[str, Any]]:
        out = [dict(row) for row in list(base_rows or [])]
        if not self._enabled:
            return out

        seen = {
            (
                _upper_text(row.get("concept_key")),
                _lower_text(row.get("alias_key")),
                _normalize_match_kind(row.get("match_kind")),
            )
            for row in out
        }
        for override in self._effective_semantic_overrides(workspace_id=workspace_id):
            row = _semantic_override_to_alias_row(override)
            if row is None:
                continue
            dedupe_key = (
                _upper_text(row.get("concept_key")),
                _lower_text(row.get("alias_key")),
                _normalize_match_kind(row.get("match_kind")),
            )
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            out.append(row)
        return out

    def resolve_concept_rows(
        self,
        *,
        base_rows: Sequence[Mapping[str, Any]],
        workspace_id: Optional[str],
    ) -> List[Dict[str, Any]]:
        out = [dict(row) for row in list(base_rows or [])]
        if not self._enabled:
            return out

        score_adjustments: Dict[str, float] = {}
        for override in self._effective_semantic_overrides(workspace_id=workspace_id):
            concept_key = _upper_text(override.get("concept_key"))
            if concept_key == "":
                continue
            delta = _score_delta_from_override(override)
            if delta == 0.0:
                continue
            score_adjustments[concept_key] = score_adjustments.get(concept_key, 0.0) + delta

        for row in out:
            concept_key = _upper_text(row.get("concept_key"))
            if concept_key == "":
                continue
            row["feedback_score_adjustment"] = round(
                float(score_adjustments.get(concept_key, 0.0)),
                6,
            )
        return out

    def resolve_domain_hints(
        self,
        *,
        domain_key: Optional[str],
        workspace_id: Optional[str],
    ) -> Dict[str, List[str]]:
        out = {
            "example_prompts": [],
            "lexical_hints": [],
            "ambiguity_notes": [],
        }
        if not self._enabled or _upper_text(domain_key) == "":
            return out

        seen = {
            "example_prompts": set(),
            "lexical_hints": set(),
            "ambiguity_notes": set(),
        }
        for override in self._effective_domain_overrides(
            workspace_id=workspace_id,
            domain_key=domain_key,
        ):
            override_type = _lower_text(override.get("override_type"))
            payload = _payload(override)
            if override_type == "add_domain_example_prompt":
                value = _optional_text(
                    payload.get("prompt") or payload.get("value") or payload.get("example")
                )
                bucket = "example_prompts"
            elif override_type == "add_domain_lexical_hint":
                value = _optional_text(
                    payload.get("hint") or payload.get("value") or payload.get("phrase")
                )
                bucket = "lexical_hints"
            elif override_type == "add_ambiguity_note":
                value = _optional_text(payload.get("note") or payload.get("value"))
                bucket = "ambiguity_notes"
            else:
                continue
            if value is None:
                continue
            dedupe_key = value.lower()
            if dedupe_key in seen[bucket]:
                continue
            seen[bucket].add(dedupe_key)
            out[bucket].append(value)
        return out

    def resolve_prompt_alias_rows(
        self,
        *,
        prompt: str,
        workspace_id: Optional[str],
    ) -> List[Dict[str, Any]]:
        if not self._enabled:
            return []

        prompt_text = str(prompt or "").strip()
        prompt_norm = _normalize_prompt(prompt_text)
        prompt_ngrams = _build_ngrams(prompt_text)
        out: List[Dict[str, Any]] = []
        for override in self._effective_semantic_overrides(workspace_id=workspace_id):
            row = _semantic_override_to_prompt_alias_row(
                override,
                prompt_norm=prompt_norm,
                prompt_ngrams=prompt_ngrams,
            )
            if row is not None:
                out.append(row)
        return out

    def _effective_semantic_overrides(
        self,
        *,
        workspace_id: Optional[str],
        concept_key: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        if not self._enabled:
            return []
        global_rows = self._semantic_override_repository.list_overrides(
            workspace_id=None,
            status="active",
        )
        workspace_rows = []
        if _optional_text(workspace_id) is not None:
            workspace_rows = self._semantic_override_repository.list_overrides(
                workspace_id=str(workspace_id).strip(),
                status="active",
            )
        concept_filter = _upper_text(concept_key)
        merged: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
        for row in list(global_rows or []):
            normalized = dict(row)
            if concept_filter and _upper_text(normalized.get("concept_key")) != concept_filter:
                continue
            merged[_override_identity(normalized)] = normalized
        for row in list(workspace_rows or []):
            normalized = dict(row)
            if concept_filter and _upper_text(normalized.get("concept_key")) != concept_filter:
                continue
            merged[_override_identity(normalized)] = normalized
        return list(merged.values())

    def _effective_domain_overrides(
        self,
        *,
        workspace_id: Optional[str],
        domain_key: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        if not self._enabled:
            return []
        global_rows = self._domain_override_repository.list_overrides(
            workspace_id=None,
            status="active",
        )
        workspace_rows = []
        if _optional_text(workspace_id) is not None:
            workspace_rows = self._domain_override_repository.list_overrides(
                workspace_id=str(workspace_id).strip(),
                status="active",
            )
        domain_filter = _upper_text(domain_key)
        merged: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
        for row in list(global_rows or []):
            normalized = dict(row)
            if domain_filter and _upper_text(normalized.get("domain_key")) != domain_filter:
                continue
            merged[_domain_override_identity(normalized)] = normalized
        for row in list(workspace_rows or []):
            normalized = dict(row)
            if domain_filter and _upper_text(normalized.get("domain_key")) != domain_filter:
                continue
            merged[_domain_override_identity(normalized)] = normalized
        return list(merged.values())


def _semantic_override_to_alias_row(
    override: Mapping[str, Any],
) -> Optional[Dict[str, Any]]:
    override_type = _lower_text(override.get("override_type"))
    payload = _payload(override)
    concept_key = _upper_text(override.get("concept_key"))
    if concept_key == "":
        return None
    if override_type == "add_alias":
        alias_key = _optional_text(payload.get("alias_key") or payload.get("alias"))
        match_kind = _normalize_match_kind(payload.get("match_kind"))
        weight = _to_float(payload.get("weight"), default=1.0)
    elif override_type == "add_phrase_hint":
        alias_key = _optional_text(
            payload.get("value") or payload.get("hint") or payload.get("phrase")
        )
        match_kind = "contains"
        weight = _to_float(payload.get("weight"), default=0.75)
    else:
        return None
    if alias_key is None:
        return None
    return {
        "concept_key": concept_key,
        "alias_key": alias_key,
        "weight": weight,
        "match_kind": match_kind,
        "source": "feedback_override",
    }


def _semantic_override_to_prompt_alias_row(
    override: Mapping[str, Any],
    *,
    prompt_norm: str,
    prompt_ngrams: Sequence[str],
) -> Optional[Dict[str, Any]]:
    alias_row = _semantic_override_to_alias_row(override)
    if alias_row is None:
        return None
    alias_key = _optional_text(alias_row.get("alias_key"))
    match_kind = _normalize_match_kind(alias_row.get("match_kind"))
    if alias_key is None or not _matches_prompt(
        alias=alias_key,
        match_kind=match_kind,
        prompt_norm=prompt_norm,
        prompt_ngrams=prompt_ngrams,
    ):
        return None
    matched_ngram = alias_key if match_kind == "exact" else _matched_ngram(alias_key, prompt_ngrams)
    return {
        "concept_key": _upper_text(alias_row.get("concept_key")),
        "semantic_concept_id": None,
        "canonical_value": alias_key,
        "alias_value": alias_key,
        "match_kind": match_kind,
        "weight": _to_float(alias_row.get("weight"), default=1.0),
        "matched_ngram": matched_ngram or alias_key,
    }


def _score_delta_from_override(override: Mapping[str, Any]) -> float:
    override_type = _lower_text(override.get("override_type"))
    payload = _payload(override)
    raw_delta = payload.get("delta", payload.get("score_delta", payload.get("weight")))
    delta = _to_float(raw_delta, default=0.0)
    if delta <= 0:
        return 0.0
    if override_type == "concept_rank_boost":
        return delta
    if override_type == "concept_rank_penalty":
        return -delta
    return 0.0


def _build_ngrams(prompt: str) -> List[str]:
    text = _normalize_prompt(prompt)
    tokens = [token for token in text.split() if token]
    out: List[str] = []
    for n in (3, 2, 1):
        for idx in range(0, max(0, len(tokens) - n + 1)):
            out.append(" ".join(tokens[idx : idx + n]))
    return list(dict.fromkeys(out))


def _normalize_prompt(value: str) -> str:
    return _PROMPT_TOKEN_RE.sub(" ", str(value or "").strip().lower()).strip()


def _matches_prompt(
    *,
    alias: str,
    match_kind: str,
    prompt_norm: str,
    prompt_ngrams: Sequence[str],
) -> bool:
    alias_norm = _normalize_prompt(alias)
    if alias_norm == "":
        return False
    if match_kind in {"exact", "normalized"}:
        return alias_norm in set(prompt_ngrams)
    if match_kind == "prefix":
        return any(token.startswith(alias_norm) for token in prompt_ngrams)
    if match_kind == "suffix":
        return any(token.endswith(alias_norm) for token in prompt_ngrams)
    if match_kind == "regex":
        try:
            return bool(re.search(alias, prompt_norm, re.IGNORECASE))
        except re.error:
            return False
    return alias_norm in prompt_norm


def _matched_ngram(alias: str, prompt_ngrams: Sequence[str]) -> str:
    alias_norm = _normalize_prompt(alias)
    for ngram in prompt_ngrams:
        if alias_norm == ngram or alias_norm in ngram:
            return ngram
    return alias_norm


def _override_identity(row: Mapping[str, Any]) -> Tuple[str, str, str]:
    return (
        _upper_text(row.get("concept_key")),
        _lower_text(row.get("override_type")),
        _lower_text(row.get("override_key")),
    )


def _domain_override_identity(row: Mapping[str, Any]) -> Tuple[str, str, str]:
    return (
        _upper_text(row.get("domain_key")),
        _lower_text(row.get("override_type")),
        _lower_text(row.get("override_key")),
    )


def _payload(row: Mapping[str, Any]) -> Dict[str, Any]:
    payload = row.get("override_value_json")
    return dict(payload) if isinstance(payload, Mapping) else {}


def _optional_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _upper_text(value: Any) -> str:
    return str(value or "").strip().upper()


def _lower_text(value: Any) -> str:
    return str(value or "").strip().lower()


def _normalize_match_kind(value: Any) -> str:
    token = _lower_text(value)
    if token in {"exact", "normalized", "contains", "prefix", "suffix", "regex"}:
        return token
    return "contains"


def _to_float(value: Any, *, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


__all__ = ["RuntimeOverrideResolver"]
