from __future__ import annotations

from app.features.flowforge.schemas.integrations import register_integration_models
from app.features.flowforge.schemas.matching import register_matching_models
from app.features.flowforge.schemas.reports import register_report_models
from app.features.flowforge.schemas.resources import register_resource_models
from app.features.flowforge.schemas.runs import register_run_models
from app.features.flowforge.schemas.settings import register_settings_models
from app.features.flowforge.schemas.workflows import register_workflow_models


def register_models(namespace):
    models = register_workflow_models(namespace)
    models.update(register_integration_models(namespace, run_event=models["run_event"]))
    models.update(register_resource_models(namespace))
    models.update(register_matching_models(namespace))
    models.update(register_run_models(namespace))
    models.update(register_report_models(namespace))
    models.update(register_settings_models(namespace))
    return {
        "workflow_definition": models["workflow_definition"],
        "workflow_definition_create": models["workflow_definition_create"],
        "workflow_version": models["workflow_version"],
        "workflow_version_create": models["workflow_version_create"],
        "validation_result": models["validation_result"],
        "run_inspector": models["run_inspector"],
        "workflow_run": models["run"],
        "workflow_run_list": models["run_list"],
        "workflow_run_event": models["run_event"],
        "workflow_run_event_list": models["run_event_list"],
        "workflow_run_note_request": models["run_note_request"],
        "human_task_list": models["human_task_list"],
        "signed_action_create_request": models["signed_action_create_request"],
        "signed_action_create_response": models["signed_action_create_response"],
        "approval_decision_request": models["approval_decision_request"],
        "approval_decision_response": models["approval_decision_response"],
        "public_signed_action": models["public_signed_action"],
        "public_signed_action_result": models["public_signed_action_result"],
        "notification_list": models["notification_list"],
        "no_match_escalation_request": models["no_match_escalation_request"],
        "no_match_escalation_response": models["no_match_escalation_response"],
        "reporting_domain": models["reporting_domain"],
        "report_summary": models["report_summary"],
        "report_dashboard": models["report_dashboard"],
        "webhook_accepted": models["webhook_accepted"],
        "integration_config": models["integration_config"],
        "integration_config_create_response": models["integration_config_create_response"],
        "integration_trigger": models["integration_trigger"],
        "resource_set": models["resource_set"],
        "resource_record": models["resource_record"],
        "resource_record_update": models["resource_record_update"],
        "resource_record_list": models["resource_record_list"],
        "snapshot_batch": models["snapshot_batch"],
        "manual_snapshot_response": models["manual_snapshot_response"],
        "matching_policy": models["matching_policy"],
        "matching_policy_version": models["matching_policy_version"],
        "matching_policy_llm_draft": models["matching_policy_llm_draft"],
        "matching_policy_llm_draft_acceptance": models["matching_policy_llm_draft_acceptance"],
        "matching_policy_validation": models["matching_policy_validation"],
        "matching_simulation": models["matching_simulation"],
        "workspace_settings": models["workspace_settings"],
        "workspace_settings_update": models["workspace_settings_update"],
    }


__all__ = ["register_models"]
