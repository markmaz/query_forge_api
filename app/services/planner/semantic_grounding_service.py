from __future__ import annotations

import inspect
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional

from sqlalchemy.exc import SQLAlchemyError

from app.services.planner.semantic_candidate_models import SemanticCandidatePayload
from app.services.planner.semantic_retrieval_service import SemanticRetrievalService
from app.services.semantic.value_alias_resolution_service import ValueAliasResolutionService

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SemanticGroundingBundle:
    candidates: Optional[SemanticCandidatePayload] = None
    alias_constraints: List[Dict[str, Any]] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def to_debug_payload(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "warnings": list(self.warnings),
            "alias_constraints": [dict(item) for item in self.alias_constraints],
        }
        if self.candidates is None:
            payload["candidate_summary"] = None
            return payload

        metadata = dict(self.candidates.metadata or {})
        payload["candidate_summary"] = {
            "base_domain_id": int(self.candidates.base_domain_id),
            "base_domain_key": self.candidates.base_domain_key,
            "semantic_source": metadata.get("semantic_source"),
            "metric_count": len(self.candidates.metric_candidates),
            "dimension_count": len(self.candidates.dimension_candidates),
            "filter_count": len(self.candidates.filter_candidates),
            "time_count": len(self.candidates.time_candidates),
            "value_count": len(self.candidates.value_candidates),
            "metrics": [row.concept_key for row in self.candidates.metric_candidates[:5]],
            "dimensions": [row.concept_key for row in self.candidates.dimension_candidates[:5]],
            "filters": [row.concept_key for row in self.candidates.filter_candidates[:5]],
            "times": [row.concept_key for row in self.candidates.time_candidates[:5]],
        }
        return payload


class SemanticGroundingService:
    def __init__(
        self,
        *,
        retrieval_service: Optional[SemanticRetrievalService] = None,
        value_alias_resolver: Optional[ValueAliasResolutionService] = None,
    ) -> None:
        self._retrieval = retrieval_service or SemanticRetrievalService()
        self._value_alias_resolver = value_alias_resolver or ValueAliasResolutionService()

    def build_grounding_bundle(
        self,
        *,
        prompt: str,
        workspace_id: str,
        base_domain_id: int,
        base_domain_name: Optional[str],
        capabilities_compact: Mapping[str, Any],
        include_candidates: bool = True,
        include_alias_constraints: bool = True,
    ) -> SemanticGroundingBundle:
        warnings: List[str] = []
        candidates: Optional[SemanticCandidatePayload] = None
        alias_constraints: List[Dict[str, Any]] = []

        if include_alias_constraints:
            alias_constraints = self.resolve_alias_constraints(
                prompt=prompt,
                workspace_id=workspace_id,
            )

        if include_candidates:
            try:
                candidates = self._retrieval.retrieve(
                    prompt=prompt,
                    workspace_id=workspace_id,
                    base_domain_id=int(base_domain_id),
                    base_domain_name=base_domain_name,
                    capabilities_compact=capabilities_compact,
                )
            except (OSError, RuntimeError, TypeError, ValueError, SQLAlchemyError) as exc:
                logger.warning("semantic grounding candidate retrieval failed err=%s", exc)
                warnings.append("candidate_retrieval_failed")

        return SemanticGroundingBundle(
            candidates=candidates,
            alias_constraints=alias_constraints,
            warnings=warnings,
        )

    def resolve_alias_constraints(
        self,
        *,
        prompt: str,
        workspace_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        try:
            rows = _resolve_alias_rows(
                self._value_alias_resolver,
                prompt=prompt,
                workspace_id=workspace_id,
            )
        except (OSError, RuntimeError, TypeError, ValueError, SQLAlchemyError) as exc:
            logger.warning("semantic grounding alias resolution failed err=%s", exc)
            return []
        return _rows_to_alias_constraints(rows)


def _rows_to_alias_constraints(rows: List[Mapping[str, Any]] | List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    constraints: List[Dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for row in list(rows or []):
        if not isinstance(row, Mapping):
            continue
        concept_key = str(row.get("concept_key") or "").strip().upper()
        explicit_canonical = str(row.get("canonical_value") or "").strip()
        canonical = str(explicit_canonical or row.get("value_hint") or "").strip()
        matched_alias = str(row.get("matched_alias") or row.get("text") or "").strip()
        if canonical == "" and matched_alias == "":
            continue
        canonical = canonical or matched_alias
        display_text = (
            canonical
            if explicit_canonical and concept_key == ""
            else (matched_alias or canonical)
        )
        dedupe_key = (concept_key, canonical.lower(), matched_alias.lower())
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        constraints.append(
            {
                "kind": (
                    str(row.get("kind") or "unknown")
                    if concept_key
                    else "unknown"
                ),
                "text": display_text,
                "op": str(row.get("op") or "eq"),
                "value_hint": canonical,
                "notes": (
                    (
                        str(row.get("notes") or "").strip()
                        if concept_key
                        else ""
                    )
                    or (f"semantic_alias:{concept_key}" if concept_key else "semantic_alias")
                ),
            }
        )
    return constraints


def _resolve_alias_rows(
    resolver: Any,
    *,
    prompt: str,
    workspace_id: Optional[str],
):
    resolve = getattr(resolver, "resolve")
    try:
        signature = inspect.signature(resolve)
    except (TypeError, ValueError):
        signature = None

    if signature is not None and "workspace_id" not in signature.parameters:
        return resolve(prompt=prompt)
    return resolve(prompt=prompt, workspace_id=workspace_id)


__all__ = ["SemanticGroundingBundle", "SemanticGroundingService"]
