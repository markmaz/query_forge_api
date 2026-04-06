from __future__ import annotations

from typing import Any, Mapping

from app.services.shared_ai.artifacts import Candidate

FLOAT_PARSE_ERRORS = (TypeError, ValueError)


def candidate_from_column_row(row: Mapping[str, Any]) -> Candidate:
    payload = dict(row)
    column_id = str(payload.get("column_id") or payload.get("workspace_column_id") or "")
    label = str(payload.get("display_name") or payload.get("column_name") or column_id)
    scores = _candidate_scores(payload)
    return Candidate(
        candidate_id=column_id,
        candidate_type="column",
        label=label,
        description=_text_or_none(payload.get("description")),
        scores=scores,
        attributes=payload,
    )


def candidate_from_domain_row(row: Mapping[str, Any]) -> Candidate:
    payload = dict(row)
    domain_id = str(payload.get("domain_id") or "")
    label = str(payload.get("name") or payload.get("domain_name") or domain_id)
    scores = _candidate_scores(payload)
    return Candidate(
        candidate_id=domain_id,
        candidate_type="domain",
        label=label,
        description=_text_or_none(payload.get("description")),
        scores=scores,
        attributes=payload,
    )


def candidate_to_dict(candidate: Candidate) -> dict[str, Any]:
    payload = dict(candidate.attributes)
    payload.setdefault("candidate_id", candidate.candidate_id)
    payload.setdefault("candidate_type", candidate.candidate_type)
    payload.setdefault("label", candidate.label)
    payload["capabilities"] = list(candidate.capabilities)
    payload.update(candidate.scores)
    return payload


def _candidate_scores(payload: Mapping[str, Any]) -> dict[str, float]:
    score_keys = (
        "score",
        "base_score",
        "policy_adjustment",
        "vector_score",
        "lexical_score",
        "combined_retrieval_score",
        "final_score",
    )
    out: dict[str, float] = {}
    for key in score_keys:
        raw = payload.get(key)
        try:
            if raw is not None:
                out[key] = float(raw)
        except FLOAT_PARSE_ERRORS:
            continue
    return out


def _text_or_none(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None
