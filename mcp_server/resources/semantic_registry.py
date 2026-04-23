from __future__ import annotations

from app.services.semantic.semantic_concept_service import SemanticConceptService
from mcp.server.fastmcp import Context, FastMCP

from ..dependencies import MCPDependencies
from ..exceptions import MCPError
from ..resource_registry import execute_resource


class SemanticRegistryResource:
    def __init__(self, *, concept_service: SemanticConceptService | None = None) -> None:
        self._concepts = concept_service or SemanticConceptService()

    def summary(self, *, concept_key: str) -> dict[str, object]:
        listing = self._concepts.list_concepts(q=concept_key, page=1, page_size=50)
        concept = next(
            (
                row
                for row in list(listing.get("rows") or [])
                if str(row.get("concept_key") or "").strip().upper() == str(concept_key or "").strip().upper()
            ),
            None,
        )
        if concept is None:
            raise MCPError(
                error_code="QUERY_NOT_FOUND",
                message=f"Semantic concept '{concept_key}' was not found",
                status_code=404,
            )
        aliases = self._concepts.list_aliases(concept_key=str(concept.get("concept_key") or "")).get("rows") or []
        return {
            "concept_key": str(concept.get("concept_key") or ""),
            "name": str(concept.get("name") or concept.get("concept_key") or ""),
            "description": str(concept.get("description") or "").strip() or None,
            "semantic_type": str(concept.get("semantic_type") or "").strip() or None,
            "entity": str(concept.get("entity") or "").strip() or None,
            "aliases": [str(row.get("alias_key") or "") for row in aliases if str(row.get("alias_key") or "").strip()],
        }


def register(mcp: FastMCP, dependencies: MCPDependencies) -> None:
    @mcp.resource(
        "qf://workspace/{workspace_id}/semantic-registry/{concept_key}",
        name="semantic_registry_summary",
        description="Concise semantic concept and alias summary for MCP grounding.",
    )
    async def semantic_registry(workspace_id: str, concept_key: str, ctx: Context) -> str:
        resource = dependencies.get_semantic_resource()
        return await execute_resource(
            name="semantic_registry_summary",
            workspace_id=workspace_id,
            request_summary={"workspace_id": workspace_id, "concept_key": concept_key},
            ctx=ctx,
            dependencies=dependencies,
            handler=lambda request_context: resource.summary(concept_key=concept_key),
        )
