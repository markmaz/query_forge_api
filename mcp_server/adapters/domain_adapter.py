from __future__ import annotations

from typing import Any

from app.exceptions.forge_error import ForgeError
from app.services.admin.domain_profile_service import DomainProfileService
from app.services.domains.capabilities_service import DomainCapabilitiesService
from app.services.query_studio.domain_explorer_service import QueryStudioDomainExplorerService
from app.services.vector.domain_index_service import DomainVectorIndexService

from ..context import RequestContext
from ..exceptions import MCPError
from ..schemas.common import CapabilityFlags
from ..schemas.domains import (
    DomainLabelValue,
    DomainProfileResponse,
    DomainSearchResult,
    SearchDomainsResponse,
)
from .helpers import confidence_from_overlap, normalize_domain_key

class DomainAdapter:
    def __init__(
        self,
        *,
        explorer_service: QueryStudioDomainExplorerService | None = None,
        profile_service: DomainProfileService | None = None,
        capabilities_service: DomainCapabilitiesService | None = None,
        vector_index_service: DomainVectorIndexService | None = None,
    ) -> None:
        self._explorer = explorer_service or QueryStudioDomainExplorerService()
        self._profiles = profile_service or DomainProfileService()
        self._capabilities = capabilities_service or DomainCapabilitiesService()
        self._vector = vector_index_service or DomainVectorIndexService()

    def list_visible_domains(self, *, request_context: RequestContext) -> list[dict[str, Any]]:
        rows = self._explorer.list_domains(
            workspace_id=request_context.workspace_id,
            user_id=request_context.user_id,
        )
        return [dict(row) for row in rows]

    def resolve_domain(self, *, request_context: RequestContext, domain_key: str) -> dict[str, Any]:
        target = normalize_domain_key(domain_key)
        if target == "":
            raise MCPError(error_code="INVALID_DOMAIN", message="domain_key is required", status_code=400)
        for row in self.list_visible_domains(request_context=request_context):
            if normalize_domain_key(row.get("key") or row.get("label") or row.get("name")) == target:
                return row
        raise MCPError(
            error_code="INVALID_DOMAIN",
            message=f"Domain '{domain_key}' is not visible in this workspace",
            status_code=404,
        )

    def search_domains(
        self,
        *,
        request_context: RequestContext,
        query: str,
        limit: int,
    ) -> SearchDomainsResponse:
        visible = self.list_visible_domains(request_context=request_context)
        visible_by_id = {
            int(row["id"]): dict(row)
            for row in visible
            if row.get("id") is not None
        }
        scored: list[dict[str, Any]] = []
        try:
            vector_rows = self._vector.search_domains(
                workspace_id=request_context.workspace_id,
                query=query,
                limit=max(limit, 10),
            ).get("results", [])
        except Exception:
            vector_rows = []

        for row in vector_rows:
            domain_id = int(row.get("domain_id") or 0)
            visible_row = visible_by_id.get(domain_id)
            if visible_row is None:
                continue
            reasons = list(row.get("reason") or [])
            capabilities = self._capability_flags(
                request_context=request_context,
                domain_id=domain_id,
            )
            scored.append(
                {
                    "domain_key": str(visible_row.get("key") or ""),
                    "name": str(visible_row.get("label") or visible_row.get("name") or ""),
                    "description": str(visible_row.get("description") or row.get("summary") or "").strip() or None,
                    "confidence": float(row.get("score") or 0.0),
                    "reasons": reasons or [f"Matched QueryForge domain vector index for '{query}'."],
                    "capabilities": capabilities,
                }
            )

        if not scored:
            for row in visible:
                confidence = confidence_from_overlap(
                    query,
                    str(row.get("label") or ""),
                    str(row.get("description") or ""),
                )
                if confidence <= 0:
                    continue
                scored.append(
                    {
                        "domain_key": str(row.get("key") or ""),
                        "name": str(row.get("label") or row.get("name") or ""),
                        "description": str(row.get("description") or "").strip() or None,
                        "confidence": confidence,
                        "reasons": ["Matched visible domain metadata lexically."],
                        "capabilities": self._capability_flags(
                            request_context=request_context,
                            domain_id=int(row["id"]),
                        ),
                    }
                )

        if not scored:
            raise MCPError(
                error_code="INVALID_DOMAIN",
                message="No visible domains matched this query",
                status_code=404,
            )

        scored.sort(key=lambda item: (-float(item["confidence"]), str(item["domain_key"])))
        return SearchDomainsResponse(
            domains=[
                DomainSearchResult(
                    domain_key=item["domain_key"],
                    name=item["name"],
                    description=item["description"],
                    confidence=float(item["confidence"]),
                    reasons=list(item["reasons"]),
                    capabilities=item["capabilities"],
                )
                for item in scored[:limit]
            ]
        )

    def get_domain_profile(
        self,
        *,
        request_context: RequestContext,
        domain_key: str,
    ) -> DomainProfileResponse:
        domain = self.resolve_domain(request_context=request_context, domain_key=domain_key)
        domain_id = int(domain["id"])
        explorer = self._explorer.get_domain_explorer(
            workspace_id=request_context.workspace_id,
            user_id=request_context.user_id,
            domain_id=domain_id,
        )
        capabilities = self._capabilities.get_domain_capabilities(
            workspace_id=request_context.workspace_id,
            user_id=request_context.user_id,
            domain_id=domain_id,
        )
        try:
            profile = self._profiles.get_profile(request_context.workspace_id, domain_id)
        except ForgeError:
            profile = {}

        recommended_fields = list(explorer.get("recommendedFields") or [])
        recommended_dimensions = [
            DomainLabelValue(
                key=str(item.get("columnKey") or item.get("key") or ""),
                label=str(item.get("label") or item.get("name") or item.get("columnKey") or ""),
            )
            for item in recommended_fields[:8]
            if str(item.get("columnKey") or item.get("key") or "").strip()
        ]
        recommended_metrics = [
            DomainLabelValue(
                key=str(item.get("metric_key") or ""),
                label=str(item.get("label") or item.get("metric_key") or ""),
            )
            for item in list(capabilities.get("domain_metrics") or [])[:8]
            if str(item.get("metric_key") or "").strip()
        ]
        time_fields = [
            str(item.get("column_key") or "")
            for item in list(capabilities.get("time_columns") or [])
            if str(item.get("column_key") or "").strip()
        ]
        supported_intents = ["listing"]
        if recommended_metrics:
            supported_intents.append("aggregate")
        if time_fields:
            supported_intents.append("trend")
        entities = list(profile.get("entities") or [])
        primary_entities = [
            str(item.get("label") or item.get("name") or item).strip()
            for item in entities
            if str(item.get("label") or item.get("name") or item).strip()
        ][:8]
        notes = str(profile.get("notes") or "").strip()
        grain_notes = [notes] if notes else []

        return DomainProfileResponse(
            domain_key=str(domain.get("key") or ""),
            name=str(domain.get("label") or domain.get("name") or ""),
            description=str(domain.get("description") or profile.get("summary") or "").strip() or None,
            grain_notes=grain_notes,
            supported_intents=supported_intents,
            primary_entities=primary_entities,
            time_fields=time_fields,
            warnings=[],
            recommended_metrics=recommended_metrics,
            recommended_dimensions=recommended_dimensions,
        )

    def domains_resource(self, *, request_context: RequestContext) -> dict[str, Any]:
        rows = self.list_visible_domains(request_context=request_context)
        return {
            "workspace_id": request_context.workspace_id,
            "domains": [
                {
                    "domain_key": str(row.get("key") or ""),
                    "name": str(row.get("label") or row.get("name") or ""),
                    "description": str(row.get("description") or "").strip() or None,
                    "field_count": int(row.get("fieldCount") or 0),
                    "metric_count": int(row.get("metricCount") or 0),
                }
                for row in rows
            ],
        }

    def _capability_flags(self, *, request_context: RequestContext, domain_id: int) -> CapabilityFlags:
        try:
            capabilities = self._capabilities.get_domain_capabilities(
                workspace_id=request_context.workspace_id,
                user_id=request_context.user_id,
                domain_id=int(domain_id),
            )
        except ForgeError:
            return CapabilityFlags()
        return CapabilityFlags(
            supports_listing=bool(capabilities.get("dimensions")),
            supports_aggregate=bool(capabilities.get("domain_metrics") or capabilities.get("overlay_metrics")),
            supports_time_filtering=bool(capabilities.get("time_columns")),
        )
