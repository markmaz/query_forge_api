from __future__ import annotations

import hashlib
from typing import Any, Callable

from app.config.llm_resolver import ResolvedLLMRuntime, build_llm_client_for_role
from app.exceptions.forge_error import ForgeError
from app.features.flowforge.llm_drafting import MatchingPolicyDraftGenerator
from app.features.flowforge.matching import MatchingPolicyEngine
from app.features.flowforge.repositories import (
    FlowForgeDataMovementRepository,
    FlowForgeIntegrationRepository,
    FlowForgeMatchingRepository,
    FlowForgeResourceRepository,
    FlowForgeRuntimeRepository,
    FlowForgeSettingsRepository,
    FlowForgeWorkflowRepository,
)


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
        matching_engine: MatchingPolicyEngine | None = None,
        matching_policy_draft_generator: MatchingPolicyDraftGenerator | None = None,
        llm_runtime_builder: Callable[..., ResolvedLLMRuntime] | None = None,
    ) -> None:
        self._resource_repository = resource_repository or FlowForgeResourceRepository()
        self._matching_repository = matching_repository or FlowForgeMatchingRepository()
        self._integration_repository = integration_repository or FlowForgeIntegrationRepository()
        self._runtime_repository = runtime_repository or FlowForgeRuntimeRepository()
        self._settings_repository = settings_repository or FlowForgeSettingsRepository()
        self._workflow_repository = workflow_repository or FlowForgeWorkflowRepository()
        self._data_movement_repository = data_movement_repository or FlowForgeDataMovementRepository()
        self._matching_engine = matching_engine or MatchingPolicyEngine()
        self._matching_policy_draft_generator = matching_policy_draft_generator or MatchingPolicyDraftGenerator()
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
