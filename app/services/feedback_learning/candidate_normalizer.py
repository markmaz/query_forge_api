from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, Mapping, Optional

from app.schemas.feedback_learning import NormalizedCandidate, ProposedChange

_CONTROL_PAYLOAD_KEYS = {"scope", "source_scope", "workspace_id", "workspace_scope_key"}
_LOWERCASE_VALUE_KEYS = {
    "change_type",
    "concept_key",
    "domain_key",
    "match_kind",
    "override_key",
    "override_type",
    "scope",
    "source_scope",
    "target_type",
}


class CandidateNormalizer:
    def normalize(
        self,
        *,
        failure_analysis_id: int,
        workspace_id: Optional[str],
        proposed_change: ProposedChange,
    ) -> NormalizedCandidate:
        workspace_token = str(workspace_id or "").strip() or None
        source_scope = _resolve_source_scope(payload=proposed_change.payload, workspace_id=workspace_token)
        effective_workspace_id = workspace_token if source_scope == "workspace" else None
        workspace_scope_key = f"workspace:{effective_workspace_id}" if effective_workspace_id else "global"

        payload_json = _normalize_payload_object(proposed_change.payload)
        concept_key, domain_key = _resolve_target_keys(
            target_type=proposed_change.target_type,
            target_key=proposed_change.target_key,
            payload_json=payload_json,
        )

        payload_hash = _build_payload_hash(
            target_type=proposed_change.target_type,
            concept_key=concept_key,
            domain_key=domain_key,
            change_type=proposed_change.change_type,
            payload_json=payload_json,
            source_scope=source_scope,
            workspace_scope_key=workspace_scope_key,
        )

        return NormalizedCandidate.model_validate(
            {
                "failure_analysis_id": int(failure_analysis_id),
                "target_type": proposed_change.target_type,
                "concept_key": concept_key,
                "domain_key": domain_key,
                "change_type": proposed_change.change_type,
                "payload_json": payload_json,
                "payload_hash": payload_hash,
                "risk_level": proposed_change.risk_level,
                "evidence_count": 1,
                "confidence": proposed_change.confidence,
                "governance_status": "pending",
                "auto_apply_eligible": False,
                "source_scope": source_scope,
                "workspace_id": effective_workspace_id,
                "workspace_scope_key": workspace_scope_key,
            }
        )


def _resolve_source_scope(*, payload: Mapping[str, Any], workspace_id: Optional[str]) -> str:
    raw_scope = str(payload.get("source_scope") or payload.get("scope") or "").strip().lower()
    if raw_scope in {"global", "workspace"}:
        return raw_scope
    return "workspace" if workspace_id else "global"


def _resolve_target_keys(
    *,
    target_type: str,
    target_key: str,
    payload_json: Dict[str, Any],
) -> tuple[Optional[str], Optional[str]]:
    payload_concept_key = _optional_text(payload_json.get("concept_key"))
    payload_domain_key = _optional_text(payload_json.get("domain_key"))
    normalized_target_key = _optional_text(target_key)

    if target_type == "semantic_override":
        return payload_concept_key or normalized_target_key, payload_domain_key
    if target_type == "domain_override":
        return payload_concept_key, payload_domain_key or normalized_target_key
    return payload_concept_key or normalized_target_key, payload_domain_key


def _build_payload_hash(
    *,
    target_type: str,
    concept_key: Optional[str],
    domain_key: Optional[str],
    change_type: str,
    payload_json: Dict[str, Any],
    source_scope: str,
    workspace_scope_key: str,
) -> str:
    canonical_payload = json.dumps(payload_json, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    hash_input = "|".join(
        [
            str(target_type or "").strip(),
            concept_key or "",
            domain_key or "",
            str(change_type or "").strip(),
            canonical_payload,
            str(source_scope or "").strip(),
            str(workspace_scope_key or "").strip(),
        ]
    )
    return hashlib.sha256(hash_input.encode("utf-8")).hexdigest()


def _normalize_payload_object(value: Mapping[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for key in sorted(value.keys()):
        if key in _CONTROL_PAYLOAD_KEYS:
            continue
        out[key] = _normalize_payload_value(value[key], key=key)
    return out


def _normalize_payload_value(value: Any, *, key: Optional[str] = None) -> Any:
    if isinstance(value, Mapping):
        return {child_key: _normalize_payload_value(value[child_key], key=child_key) for child_key in sorted(value.keys())}
    if isinstance(value, list):
        return [_normalize_payload_value(item, key=key) for item in value]
    if isinstance(value, str):
        text = value.strip()
        if key in _LOWERCASE_VALUE_KEYS:
            return text.lower()
        return text
    return value


def _optional_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


__all__ = ["CandidateNormalizer"]
