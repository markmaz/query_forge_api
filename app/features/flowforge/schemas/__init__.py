from __future__ import annotations

from app.features.flowforge.schemas.communication_templates import register_communication_template_models
from app.features.flowforge.schemas.data_movement import register_data_movement_models
from app.features.flowforge.schemas.integrations import register_integration_models
from app.features.flowforge.schemas.matching import register_matching_models
from app.features.flowforge.schemas.reports import register_report_models
from app.features.flowforge.schemas.resources import register_resource_models
from app.features.flowforge.schemas.runs import register_run_models
from app.features.flowforge.schemas.settings import register_settings_models
from app.features.flowforge.schemas.workflows import register_workflow_models


def register_models(namespace):
    models = register_workflow_models(namespace)
    models.update(register_communication_template_models(namespace))
    models.update(register_integration_models(namespace, run_event=models["run_event"]))
    models.update(register_resource_models(namespace))
    models.update(register_matching_models(namespace))
    models.update(register_run_models(namespace))
    models.update(register_data_movement_models(namespace))
    models.update(register_report_models(namespace))
    models.update(register_settings_models(namespace))
    return {
        "workflow_definition": models["workflow_definition"],
        "workflow_definition_create": models["workflow_definition_create"],
        "workflow_ai_draft_request": models["workflow_ai_draft_request"],
        "workflow_ai_draft": models["workflow_ai_draft"],
        "workflow_version": models["workflow_version"],
        "workflow_version_create": models["workflow_version_create"],
        "workflow_permissions": models["workflow_permissions"],
        "workflow_permissions_update": models["workflow_permissions_update"],
        "workflow_owner_update": models["workflow_owner_update"],
        "workflow_run_as_update": models["workflow_run_as_update"],
        "workflow_run_as_principals": models["workflow_run_as_principals"],
        "workflow_manual_run_request": models["workflow_manual_run_request"],
        "workflow_manual_run": models["workflow_manual_run"],
        "validation_result": models["validation_result"],
        "run_inspector": models["run_inspector"],
        "workflow_run": models["run"],
        "workflow_run_list": models["run_list"],
        "workflow_run_event": models["run_event"],
        "workflow_run_event_list": models["run_event_list"],
        "workflow_run_note_request": models["run_note_request"],
        "human_task_list": models["human_task_list"],
        "human_task_queue": models["human_task_queue"],
        "signed_action_create_request": models["signed_action_create_request"],
        "signed_action_create_response": models["signed_action_create_response"],
        "approval_decision_request": models["approval_decision_request"],
        "approval_decision_response": models["approval_decision_response"],
        "public_signed_action": models["public_signed_action"],
        "public_signed_action_result": models["public_signed_action_result"],
        "notification_list": models["notification_list"],
        "data_source": models["data_source"],
        "data_source_upsert": models["data_source_upsert"],
        "data_destination": models["data_destination"],
        "data_destination_upsert": models["data_destination_upsert"],
        "data_movement_enabled_update": models["data_movement_enabled_update"],
        "data_movement_connection_test": models["data_movement_connection_test"],
        "dataset_artifact": models["dataset_artifact"],
        "dataset_artifact_list": models["dataset_artifact_list"],
        "data_movement_audit": models["data_movement_audit"],
        "data_movement_audit_list": models["data_movement_audit_list"],
        "no_match_escalation_request": models["no_match_escalation_request"],
        "no_match_escalation_response": models["no_match_escalation_response"],
        "reporting_domain": models["reporting_domain"],
        "reporting_domain_sync": models["reporting_domain_sync"],
        "report_summary": models["report_summary"],
        "report_dashboard": models["report_dashboard"],
        "intake_review_timeline": models["intake_review_timeline"],
        "intake_raw_form": models["intake_raw_form"],
        "webhook_accepted": models["webhook_accepted"],
        "integration_config": models["integration_config"],
        "integration_config_create_response": models["integration_config_create_response"],
        "integration_trigger": models["integration_trigger"],
        "workflow_value_schema": models["workflow_value_schema"],
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
        "communication_template": models["communication_template"],
        "communication_template_upsert": models["communication_template_upsert"],
        "communication_template_validation": models["communication_template_validation"],
        "communication_template_test_send": models["communication_template_test_send"],
        "communication_template_test_send_result": models["communication_template_test_send_result"],
        "communication_template_ai_draft": models["communication_template_ai_draft"],
    }


__all__ = ["register_models"]
