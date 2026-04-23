from __future__ import annotations

from typing import Optional

from app.services.dictionary.dictionary_service import DictionaryService
from app.services.domains.capabilities_service import DomainCapabilitiesService

from ..context import RequestContext
from ..exceptions import MCPError
from ..schemas.dictionary import DictionarySearchResult, SearchDictionaryResponse
from .domain_adapter import DomainAdapter
from .helpers import confidence_from_overlap, dedupe_by_key

class DictionaryAdapter:
    def __init__(
        self,
        *,
        dictionary_service: DictionaryService | None = None,
        capabilities_service: DomainCapabilitiesService | None = None,
        domain_adapter: DomainAdapter | None = None,
    ) -> None:
        self._dictionary = dictionary_service or DictionaryService()
        self._capabilities = capabilities_service or DomainCapabilitiesService()
        self._domains = domain_adapter or DomainAdapter(capabilities_service=self._capabilities)

    def search_dictionary(
        self,
        *,
        request_context: RequestContext,
        query: str,
        domain_key: Optional[str],
        types: list[str],
        limit: int,
    ) -> SearchDictionaryResponse:
        requested_types = {str(item or "").strip().lower() for item in types if str(item or "").strip()}
        if not requested_types:
            requested_types = {"column", "metric", "dimension", "filter"}

        constrained_domain = (
            self._domains.resolve_domain(request_context=request_context, domain_key=domain_key)
            if domain_key
            else None
        )
        constrained_capabilities = None
        if constrained_domain is not None:
            constrained_capabilities = self._capabilities.get_domain_capabilities(
                workspace_id=request_context.workspace_id,
                user_id=request_context.user_id,
                domain_id=int(constrained_domain["id"]),
            )

        results: list[dict[str, object]] = []

        if "column" in requested_types:
            payload = self._dictionary.search_columns(
                workspace_id=request_context.workspace_id,
                q=query,
                limit=min(limit, 50),
                active_only=True,
            )
            for row in list(payload.get("rows") or []):
                domain_value = str(constrained_domain.get("key") or "") if constrained_domain else None
                if constrained_capabilities is not None:
                    allowed_keys = {
                        str(item.get("column_key") or "").strip().lower()
                        for item in list(constrained_capabilities.get("dimensions") or [])
                    }
                    candidate_key = f"wt{row.get('workspace_table_id')}.{str(row.get('column_name') or '').strip().lower()}"
                    if candidate_key not in allowed_keys:
                        continue
                results.append(
                    {
                        "type": "column",
                        "key": f"wt{row.get('workspace_table_id')}.{str(row.get('column_name') or '').strip().lower()}",
                        "label": str(row.get("column_name") or ""),
                        "description": str(row.get("description") or "").strip() or None,
                        "table": str(row.get("table_name") or "").strip() or None,
                        "domain_key": domain_value,
                        "confidence": confidence_from_overlap(
                            query,
                            str(row.get("column_name") or ""),
                            str(row.get("description") or ""),
                            str(row.get("table_name") or ""),
                        ),
                        "aliases": [],
                    }
                )

        capability_sources: list[dict[str, object]] = []
        if constrained_domain is not None:
            capability_sources = [dict(constrained_domain)]
        else:
            capability_sources = self._domains.list_visible_domains(request_context=request_context)

        for domain_row in capability_sources:
            caps = constrained_capabilities
            if caps is None:
                caps = self._capabilities.get_domain_capabilities(
                    workspace_id=request_context.workspace_id,
                    user_id=request_context.user_id,
                    domain_id=int(domain_row["id"]),
                )
            domain_value = str(domain_row.get("key") or "")
            if "metric" in requested_types:
                for metric in list(caps.get("domain_metrics") or []):
                    metric_key = str(metric.get("metric_key") or "").strip()
                    if metric_key == "":
                        continue
                    confidence = confidence_from_overlap(query, metric_key, metric.get("label"))
                    if confidence <= 0:
                        continue
                    results.append(
                        {
                            "type": "metric",
                            "key": metric_key,
                            "label": str(metric.get("label") or metric_key),
                            "description": f"{metric.get('kind') or 'metric'} metric",
                            "table": None,
                            "domain_key": domain_value,
                            "confidence": confidence,
                            "aliases": [],
                        }
                    )
            for dimension in list(caps.get("dimensions") or []):
                if "dimension" in requested_types:
                    confidence = confidence_from_overlap(query, dimension.get("column_key"), dimension.get("label"))
                    if confidence > 0:
                        results.append(
                            {
                                "type": "dimension",
                                "key": str(dimension.get("column_key") or ""),
                                "label": str(dimension.get("label") or dimension.get("column_key") or ""),
                                "description": str(dimension.get("semantic_type") or "dimension"),
                                "table": str(dimension.get("table_name") or "").strip() or None,
                                "domain_key": domain_value,
                                "confidence": confidence,
                                "aliases": [],
                            }
                        )
                if "filter" in requested_types and bool(dimension.get("filterable")):
                    confidence = confidence_from_overlap(query, dimension.get("column_key"), dimension.get("label"))
                    if confidence > 0:
                        results.append(
                            {
                                "type": "filter",
                                "key": str(dimension.get("column_key") or ""),
                                "label": str(dimension.get("label") or dimension.get("column_key") or ""),
                                "description": "filterable field",
                                "table": str(dimension.get("table_name") or "").strip() or None,
                                "domain_key": domain_value,
                                "confidence": confidence,
                                "aliases": [],
                            }
                        )

        if not results:
            raise MCPError(
                error_code="VALIDATION_FAILED",
                message="No dictionary entries matched this query",
                status_code=404,
            )

        rows = dedupe_by_key(
            sorted(results, key=lambda item: (-float(item["confidence"]), str(item["key"]))),
            key_name="key",
        )
        return SearchDictionaryResponse(results=[DictionarySearchResult(**row) for row in rows[:limit]])
