from __future__ import annotations

from app.features.flowforge.service.approval_tasks import FlowForgeApprovalTaskServiceMixin
from app.features.flowforge.service.base import FlowForgeServiceBase
from app.features.flowforge.service.data_movement import FlowForgeDataMovementServiceMixin
from app.features.flowforge.service.integrations import FlowForgeIntegrationServiceMixin
from app.features.flowforge.service.matching_policies import FlowForgeMatchingPolicyServiceMixin
from app.features.flowforge.service.notifications import FlowForgeNotificationServiceMixin
from app.features.flowforge.service.reports import FlowForgeReportServiceMixin
from app.features.flowforge.service.resources import FlowForgeResourceServiceMixin
from app.features.flowforge.service.runs import FlowForgeRunServiceMixin
from app.features.flowforge.service.settings import FlowForgeSettingsServiceMixin
from app.features.flowforge.service.signed_actions import FlowForgeSignedActionServiceMixin
from app.features.flowforge.service.trigger_evaluation import FlowForgeTriggerEvaluationServiceMixin
from app.features.flowforge.service.webhooks import FlowForgeWebhookServiceMixin
from app.features.flowforge.service.workflows import FlowForgeWorkflowServiceMixin


class FlowForgeService(
    FlowForgeWorkflowServiceMixin,
    FlowForgeApprovalTaskServiceMixin,
    FlowForgeDataMovementServiceMixin,
    FlowForgeIntegrationServiceMixin,
    FlowForgeResourceServiceMixin,
    FlowForgeRunServiceMixin,
    FlowForgeSettingsServiceMixin,
    FlowForgeSignedActionServiceMixin,
    FlowForgeNotificationServiceMixin,
    FlowForgeReportServiceMixin,
    FlowForgeMatchingPolicyServiceMixin,
    FlowForgeWebhookServiceMixin,
    FlowForgeTriggerEvaluationServiceMixin,
    FlowForgeServiceBase,
):
    pass


__all__ = ["FlowForgeService"]
