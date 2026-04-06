from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Mapping, Optional, Protocol, Sequence

from pydantic import BaseModel, ValidationError

from app.config.llm_resolver import build_llm_client_for_role
from app.constants.llm_roles import LLMRole
from app.services.llm.llm_client import LLMClient
from app.services.semantic.catalog.catalog_models import (
    ColumnEnrichment,
    ColumnProfile,
    EnrichedColumnProfile,
)

logger = logging.getLogger(__name__)
LLM_ENRICHMENT_FALLBACK_ERRORS = (OSError, RuntimeError, TypeError, ValueError)


class _LLMBatchResponse(BaseModel):
    items: List[ColumnEnrichment]


class SemanticEnrichmentLLMInterface(Protocol):
    def enrich_batch(
        self,
        *,
        profiles: Sequence[ColumnProfile],
        workspace_id: str,
        vertical_norm: str,
        domain_name: Optional[str],
        llm_id: Optional[int] = None,
    ) -> List[ColumnEnrichment]:
        ...


class LLMSemanticEnrichmentClient:
    """
    Isolated LLM adapter for semantic enrichment.
    Keeps provider-specific behavior outside the orchestration service.
    """

    def __init__(self, *, llm_client: Optional[LLMClient] = None, max_tokens: int = 1400) -> None:
        self._explicit_llm = llm_client is not None
        self._llm = llm_client or LLMClient()
        self._max_tokens = max(300, int(max_tokens))
        self._llm_runtime_meta: Dict[str, Any] = {
            "source": "bootstrap",
            "role": LLMRole.ENRICHMENT,
            "llm_id": None,
            "provider": "generic",
            "model": str(getattr(self._llm, "_model", "") or ""),
            "endpoint": str(getattr(self._llm, "_endpoint", "") or ""),
        }

    def enrich_batch(
        self,
        *,
        profiles: Sequence[ColumnProfile],
        workspace_id: str,
        vertical_norm: str,
        domain_name: Optional[str],
        llm_id: Optional[int] = None,
    ) -> List[ColumnEnrichment]:
        if not profiles:
            return []
        if not self._explicit_llm:
            resolved = build_llm_client_for_role(
                workspace_id=str(workspace_id or "").strip(),
                role=LLMRole.ENRICHMENT,
                llm_id_override=llm_id,
                timeout_seconds=None,
            )
            self._llm = resolved.client
            self._llm_runtime_meta = {
                "source": resolved.source,
                "role": resolved.role,
                "llm_id": resolved.llm_id,
                "provider": resolved.provider,
                "model": resolved.model,
                "endpoint": resolved.endpoint,
            }

        cards = [
            {
                "table_name": p.table_name,
                "column_name": p.column_name,
                "data_type": p.data_type,
                "nullable": p.nullable,
                "distinct_count": p.distinct_count,
                "row_count": p.row_count,
                "sample_values": p.sample_values[:8],
                "is_identifier": p.is_identifier,
                "is_numeric": p.is_numeric,
                "is_date_like": p.is_date_like,
                "is_enum_like": p.is_enum_like,
                "is_dimension_candidate": p.is_dimension_candidate,
                "is_measure_candidate": p.is_measure_candidate,
            }
            for p in profiles
        ]

        prompt_payload = {
            "vertical_norm": vertical_norm,
            "domain_name": domain_name,
            "cards": cards,
        }

        system_prompt = (
            "You are a semantic column enrichment engine for a query planner. "
            "Return JSON only. Never return markdown or prose. "
            "Use only evidence from each input card."
        )
        user_prompt = (
            "Classify each column card and return strict JSON with top-level key 'items'. "
            "Rules: do not invent fields, aliases should be concise, confidence in [0,1], "
            "planner_role should be one of dimension, measure, metric, filter, time_field, identifier, other. "
            "semantic_type should be one of domain, measure, metric, dimension, filter, time_field, identifier, attribute, other. "
            f"Input:\n{json.dumps(prompt_payload, ensure_ascii=True)}"
        )

        schema = {
            "type": "json_schema",
            "json_schema": {
                "name": "semantic_enrichment_batch_v1",
                "strict": True,
                "schema": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["items"],
                    "properties": {
                        "items": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "additionalProperties": False,
                                "required": [
                                    "business_label",
                                    "semantic_type",
                                    "planner_role",
                                    "description",
                                    "aliases",
                                    "groupable",
                                    "filterable",
                                    "time_candidate",
                                    "measure_candidate",
                                    "default_aggregations",
                                    "confidence",
                                    "domain_hint",
                                ],
                                "properties": {
                                    "business_label": {"type": "string"},
                                    "semantic_type": {"type": "string"},
                                    "planner_role": {"type": "string"},
                                    "description": {"type": "string"},
                                    "aliases": {"type": "array", "items": {"type": "string"}},
                                    "groupable": {"type": "boolean"},
                                    "filterable": {"type": "boolean"},
                                    "time_candidate": {"type": "boolean"},
                                    "measure_candidate": {"type": "boolean"},
                                    "default_aggregations": {"type": "array", "items": {"type": "string"}},
                                    "confidence": {"type": "number"},
                                    "domain_hint": {"type": ["string", "null"]},
                                },
                            },
                        }
                    },
                },
            },
        }

        trace = self._llm.chat_json_with_trace(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_format=schema,
            max_tokens=self._max_tokens,
        )
        parsed = trace.get("parsed") if isinstance(trace.get("parsed"), Mapping) else None
        if not isinstance(parsed, Mapping):
            raw = str(trace.get("content") or trace.get("raw_text") or "")
            parsed = _extract_first_json_obj(raw)

        if not isinstance(parsed, Mapping):
            raise ValueError("LLM enrichment response was not valid JSON")

        try:
            output = _LLMBatchResponse.model_validate(dict(parsed))
        except ValidationError as exc:
            raise ValueError(f"LLM enrichment schema validation failed: {exc}") from exc

        if len(output.items) != len(profiles):
            raise ValueError(
                f"LLM enrichment item count mismatch: expected {len(profiles)}, got {len(output.items)}"
            )
        return list(output.items)


class SemanticEnrichmentService:
    """
    Stage 2: heuristic-first + optional LLM semantic enrichment.

    Heuristics run before LLM to reduce ambiguity and provide deterministic fallback.
    """

    def __init__(
        self,
        *,
        llm_adapter: Optional[SemanticEnrichmentLLMInterface] = None,
        batch_size: int = 25,
        enable_llm: bool = True,
    ) -> None:
        self._llm = llm_adapter or LLMSemanticEnrichmentClient()
        self._batch_size = max(1, int(batch_size))
        self._enable_llm = bool(enable_llm)

    def enrich_profiles(
        self,
        *,
        profiles: Sequence[ColumnProfile],
        workspace_id: str,
        vertical_norm: str,
        domain_name: Optional[str],
        llm_id: Optional[int] = None,
    ) -> List[EnrichedColumnProfile]:
        profile_list = list(profiles or [])
        if not profile_list:
            return []

        heuristic = [
            _heuristic_enrichment(profile=profile, domain_name=domain_name)
            for profile in profile_list
        ]
        if not self._enable_llm:
            return [
                EnrichedColumnProfile(profile=profile_list[idx], enrichment=heuristic[idx])
                for idx in range(len(profile_list))
            ]

        merged: List[EnrichedColumnProfile] = []
        for start in range(0, len(profile_list), self._batch_size):
            batch_profiles = profile_list[start : start + self._batch_size]
            batch_heuristics = heuristic[start : start + self._batch_size]
            try:
                llm_items = self._llm.enrich_batch(
                    profiles=batch_profiles,
                    workspace_id=workspace_id,
                    vertical_norm=vertical_norm,
                    domain_name=domain_name,
                    llm_id=llm_id,
                )
                for idx, profile in enumerate(batch_profiles):
                    merged_item = _merge_with_heuristic(llm_items[idx], batch_heuristics[idx], profile=profile)
                    merged.append(EnrichedColumnProfile(profile=profile, enrichment=merged_item))
            except LLM_ENRICHMENT_FALLBACK_ERRORS as exc:
                logger.warning(
                    "semantic_catalog enrichment fallback used for batch start=%s size=%s err=%s",
                    start,
                    len(batch_profiles),
                    exc,
                )
                for idx, profile in enumerate(batch_profiles):
                    merged.append(EnrichedColumnProfile(profile=profile, enrichment=batch_heuristics[idx]))
        return merged


def _merge_with_heuristic(
    llm_item: ColumnEnrichment,
    heuristic: ColumnEnrichment,
    *,
    profile: ColumnProfile,
) -> ColumnEnrichment:
    # Keep LLM flexible, but force hard planner-safe constraints.
    semantic_type = llm_item.semantic_type
    planner_role = llm_item.planner_role

    if profile.is_date_like:
        semantic_type = "time_field"
        planner_role = "time_field"
    elif profile.is_identifier:
        semantic_type = "identifier"
        planner_role = "identifier"
    elif profile.is_measure_candidate and semantic_type not in {"measure", "metric"}:
        semantic_type = "measure"
        planner_role = "measure"

    default_aggs = list(llm_item.default_aggregations or [])
    if profile.is_measure_candidate and not default_aggs:
        default_aggs = list(heuristic.default_aggregations)

    aliases = llm_item.aliases or heuristic.aliases
    if not aliases:
        aliases = [_humanize(profile.column_name)]

    return ColumnEnrichment(
        business_label=llm_item.business_label or heuristic.business_label,
        semantic_type=semantic_type,
        planner_role=planner_role,
        description=llm_item.description or heuristic.description,
        aliases=aliases,
        groupable=bool(llm_item.groupable if llm_item.groupable is not None else heuristic.groupable),
        filterable=bool(llm_item.filterable if llm_item.filterable is not None else heuristic.filterable),
        time_candidate=bool(profile.is_date_like or llm_item.time_candidate),
        measure_candidate=bool(profile.is_measure_candidate or llm_item.measure_candidate),
        default_aggregations=default_aggs,
        confidence=max(float(heuristic.confidence), float(llm_item.confidence)),
        domain_hint=llm_item.domain_hint or heuristic.domain_hint,
    )


def _heuristic_enrichment(*, profile: ColumnProfile, domain_name: Optional[str]) -> ColumnEnrichment:
    name = profile.column_name.lower()
    label = _humanize(profile.column_name)
    semantic_type = "dimension"
    planner_role = "dimension"
    default_aggs: List[str] = []
    groupable = True
    measure_candidate = False
    time_candidate = False
    confidence = 0.65

    if profile.is_date_like:
        semantic_type = "time_field"
        planner_role = "time_field"
        time_candidate = True
        confidence = 0.9
    elif profile.is_identifier:
        semantic_type = "identifier"
        planner_role = "identifier"
        confidence = 0.88
    elif profile.is_measure_candidate:
        measure_candidate = True
        if _is_count_like(name):
            semantic_type = "metric"
            planner_role = "metric"
            default_aggs = ["sum"]
        else:
            semantic_type = "measure"
            planner_role = "measure"
            default_aggs = ["sum", "avg", "min", "max"]
        groupable = False
        confidence = 0.86
    elif profile.is_enum_like:
        semantic_type = "filter"
        planner_role = "filter"
        confidence = 0.8

    description = (
        f"{label} from {profile.table_name}.{profile.column_name}. "
        f"Detected as {semantic_type} for planner role {planner_role}."
    )
    aliases = _alias_suggestions(profile.column_name)

    return ColumnEnrichment(
        business_label=label,
        semantic_type=semantic_type,  # type: ignore[arg-type]
        planner_role=planner_role,  # type: ignore[arg-type]
        description=description,
        aliases=aliases,
        groupable=groupable,
        filterable=True,
        time_candidate=time_candidate,
        measure_candidate=measure_candidate,
        default_aggregations=default_aggs,
        confidence=confidence,
        domain_hint=domain_name,
    )


def _alias_suggestions(column_name: str) -> List[str]:
    base = str(column_name or "").strip()
    if base == "":
        return []
    human = _humanize(base)
    compact = base.replace("_", " ").strip()
    out = [human]
    if compact.lower() != human.lower():
        out.append(compact)
    dedup: List[str] = []
    seen: set[str] = set()
    for token in out:
        key = token.lower()
        if key in seen:
            continue
        seen.add(key)
        dedup.append(token)
    return dedup[:5]


def _humanize(value: str) -> str:
    token = str(value or "").strip().replace("_", " ")
    token = re.sub(r"\s+", " ", token)
    return token.title()


def _is_count_like(name: str) -> bool:
    token = str(name or "").strip().lower()
    return any(piece in token for piece in ("count", "qty", "quantity", "num_", "_num"))


def _extract_first_json_obj(raw: str) -> Optional[Dict[str, Any]]:
    text = str(raw or "").strip()
    if text == "":
        return None
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return dict(parsed)
    except (TypeError, ValueError, json.JSONDecodeError):
        pass
    decoder = json.JSONDecoder()
    for idx, ch in enumerate(text):
        if ch != "{":
            continue
        try:
            parsed, _ = decoder.raw_decode(text[idx:])
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if isinstance(parsed, dict):
            return dict(parsed)
    return None
