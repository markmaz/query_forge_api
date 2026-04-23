from __future__ import annotations

from app.services.domain.planner_domain_selection_policy_service import PlannerDomainSelectionPolicyService
from app.services.domain.planner_projection_policy_service import PlannerProjectionPolicyService
from app.services.domain.planner_prompt_intent_policy_service import PlannerPromptIntentPolicyService
from app.services.domain.planner_retrieval_policy_service import PlannerRetrievalPolicyService
from app.services.domain.planner_signal_policy_service import PlannerSignalPolicyService
from app.services.domain.planner_semantic_join_policy_service import PlannerSemanticJoinPolicyService
from app.services.domain.planner_semantic_projection_policy_service import PlannerSemanticProjectionPolicyService
from app.services.domain.planner_semantic_time_policy_service import PlannerSemanticTimePolicyService
from mcp.server.fastmcp import Context, FastMCP

from ..dependencies import MCPDependencies
from ..resource_registry import execute_resource


class PlannerPolicyResource:
    def summary(self, *, workspace_id: str) -> dict[str, object]:
        families = []
        for family, rows in (
            ("signal", PlannerSignalPolicyService().list_policies(workspace_id=workspace_id).get("policies") or []),
            ("prompt_intent", PlannerPromptIntentPolicyService().list_policies(workspace_id=workspace_id).get("policies") or []),
            ("projection", PlannerProjectionPolicyService().list_policies(workspace_id=workspace_id).get("policies") or []),
            ("retrieval", PlannerRetrievalPolicyService().list_policies(workspace_id=workspace_id).get("policies") or []),
            ("domain_selection", PlannerDomainSelectionPolicyService().list_policies(workspace_id=workspace_id).get("policies") or []),
            ("semantic_join", PlannerSemanticJoinPolicyService().get_applicable_policies()),
            ("semantic_projection", PlannerSemanticProjectionPolicyService().get_applicable_policies()),
            ("semantic_time", PlannerSemanticTimePolicyService().get_applicable_policies()),
        ):
            keys = [
                str(row.get("policy_key") or "")
                for row in list(rows)[:5]
                if str(row.get("policy_key") or "").strip()
            ]
            families.append(
                {
                    "family": family,
                    "count": len(list(rows)),
                    "sample_policy_keys": keys,
                }
            )
        return {
            "workspace_id": workspace_id,
            "families": families,
            "notes": [
                "This resource is a concise summary intended for MCP grounding, not a full policy export.",
            ],
        }


def register(mcp: FastMCP, dependencies: MCPDependencies) -> None:
    @mcp.resource(
        "qf://workspace/{workspace_id}/planner-policies",
        name="planner_policy_summary",
        description="Concise summary of planner and semantic policy families relevant to QueryForge MCP callers.",
    )
    async def planner_policies(workspace_id: str, ctx: Context) -> str:
        resource = dependencies.get_policy_resource()
        return await execute_resource(
            name="planner_policy_summary",
            workspace_id=workspace_id,
            request_summary={"workspace_id": workspace_id},
            ctx=ctx,
            dependencies=dependencies,
            handler=lambda request_context: resource.summary(workspace_id=request_context.workspace_id),
        )
