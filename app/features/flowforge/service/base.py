from __future__ import annotations

import hashlib
from typing import Any, Callable

from app.config.llm_resolver import ResolvedLLMRuntime, build_llm_client_for_role
from app.exceptions.forge_error import ForgeError
from app.features.flowforge.communication_template_drafting import CommunicationTemplateDraftGenerator
from app.features.flowforge.llm_drafting import MatchingPolicyDraftGenerator
from app.features.flowforge.matching import MatchingPolicyEngine
from app.features.flowforge.permissions import WorkflowPermissionService
from app.features.flowforge.workflow_drafting import WorkflowGraphDraftGenerator
from app.features.flowforge.repositories import (
    FlowForgeCommunicationTemplateRepository,
    FlowForgeDataMovementRepository,
    FlowForgeIntegrationRepository,
    FlowForgeMatchingRepository,
    FlowForgeResourceRepository,
    FlowForgeRuntimeRepository,
    FlowForgeSettingsRepository,
    FlowForgeWorkflowRepository,
)
from app.features.flowforge.runtime.communication_templates import CommunicationTemplateRenderer


class FlowForgeServiceBase:
    def __init__(
        self,
        *,
        resource_repository: FlowForgeResourceRepository | None = None,
        matching_repository: FlowForgeMatchingRepository | None = None,
        integration_repository: FlowForgeIntegrationRepository | None = None,
        runtime_repository: FlowForgeRuntimeRepository | None = None,
        settings_repository: FlowForgeSettingsRepository | None = None,
        workflow_repository: FlowForgeWorkflowRepository | None = None,
        data_movement_repository: FlowForgeDataMovementRepository | None = None,
        communication_template_repository: FlowForgeCommunicationTemplateRepository | None = None,
        matching_engine: MatchingPolicyEngine | None = None,
        communication_template_renderer: CommunicationTemplateRenderer | None = None,
        matching_policy_draft_generator: MatchingPolicyDraftGenerator | None = None,
        communication_template_draft_generator: CommunicationTemplateDraftGenerator | None = None,
        workflow_graph_draft_generator: WorkflowGraphDraftGenerator | None = None,
        workflow_permission_service: WorkflowPermissionService | None = None,
        communication_template_email_sender: Callable[[str, str, str], None] | None = None,
        llm_runtime_builder: Callable[..., ResolvedLLMRuntime] | None = None,
    ) -> None:
        self._resource_repository = resource_repository or FlowForgeResourceRepository()
        self._matching_repository = matching_repository or FlowForgeMatchingRepository()
        self._integration_repository = integration_repository or FlowForgeIntegrationRepository()
        self._runtime_repository = runtime_repository or FlowForgeRuntimeRepository()
        self._settings_repository = settings_repository or FlowForgeSettingsRepository()
        self._workflow_repository = workflow_repository or FlowForgeWorkflowRepository()
        self._data_movement_repository = data_movement_repository or FlowForgeDataMovementRepository()
        self._communication_template_repository = communication_template_repository or FlowForgeCommunicationTemplateRepository()
        self._matching_engine = matching_engine or MatchingPolicyEngine()
        self._communication_template_renderer = communication_template_renderer or CommunicationTemplateRenderer()
        self._matching_policy_draft_generator = matching_policy_draft_generator or MatchingPolicyDraftGenerator()
        self._communication_template_draft_generator = communication_template_draft_generator or CommunicationTemplateDraftGenerator()
        self._workflow_graph_draft_generator = workflow_graph_draft_generator or WorkflowGraphDraftGenerator()
        self._workflow_permission_service = workflow_permission_service or WorkflowPermissionService(
            workflow_repository=self._workflow_repository
        )
        self._communication_template_email_sender = communication_template_email_sender or self._send_communication_template_email
        self._llm_runtime_builder = llm_runtime_builder or build_llm_client_for_role

    def _optional_string(self, value: Any) -> str | None:
        text = str(value or "").strip()
        return text or None

    def _positive_int(self, value: Any, *, field_name: str) -> int:
        try:
            number = int(value)
        except (TypeError, ValueError):
            raise ForgeError(f"{field_name} must be a positive integer.", status_code=400) from None
        if number < 1:
            raise ForgeError(f"{field_name} must be a positive integer.", status_code=400)
        return number

    def _optional_positive_int(self, value: Any, *, field_name: str) -> int | None:
        if value is None or value == "":
            return None
        return self._positive_int(value, field_name=field_name)

    def _hash_webhook_secret(self, value: str) -> str:
        return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()

    @staticmethod
    def _send_communication_template_email(recipient: str, subject: str, html: str) -> None:
        from app.email.mailer import get_logo, send_email

        send_email(get_logo(), subject, recipient, html)
