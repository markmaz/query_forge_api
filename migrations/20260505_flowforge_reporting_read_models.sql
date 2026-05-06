CREATE OR REPLACE VIEW v_flowforge_report_workflow_runs AS
SELECT
  id,
  workspace_id,
  workflow_definition_id,
  workflow_version_id,
  intake_event_id,
  mode,
  status,
  current_node_id,
  started_at,
  completed_at,
  failed_at,
  created_at,
  updated_at
FROM flowforge_runs;

CREATE OR REPLACE VIEW v_flowforge_report_intake_events AS
SELECT
  id,
  workspace_id,
  integration_config_id,
  provider,
  external_form_id,
  external_submission_id,
  mode,
  received_at,
  status,
  error_code,
  created_at,
  updated_at
FROM flowforge_intake_events;

CREATE OR REPLACE VIEW v_flowforge_report_matching_evaluations AS
SELECT
  e.id,
  e.workspace_id,
  e.run_id,
  r.mode AS run_mode,
  e.matching_policy_version_id,
  e.resource_set_id,
  e.snapshot_batch_id,
  e.selected_source_record_key,
  e.no_match_reason,
  e.status,
  e.evaluated_at
FROM flowforge_matching_evaluations e
LEFT JOIN flowforge_runs r
  ON r.workspace_id = e.workspace_id
 AND r.id = e.run_id;

CREATE OR REPLACE VIEW v_flowforge_report_resource_snapshots AS
SELECT
  rs.id,
  rs.workspace_id,
  rs.resource_set_id,
  rs.snapshot_batch_id,
  b.mode AS snapshot_mode,
  rs.source_record_key,
  rs.display_name,
  rs.effective_status,
  rs.availability_status,
  rs.capacity_total,
  rs.capacity_used,
  rs.capacity_available,
  rs.current_load,
  rs.service_area,
  rs.timezone,
  rs.validation_status,
  rs.source_missing,
  rs.compiled_at,
  rs.source_updated_at
FROM flowforge_resource_snapshot_records rs
LEFT JOIN flowforge_resource_snapshot_batches b
  ON b.workspace_id = rs.workspace_id
 AND b.id = rs.snapshot_batch_id;

CREATE OR REPLACE VIEW v_flowforge_report_offers_responses AS
SELECT
  h.id,
  h.workspace_id,
  h.run_id,
  r.mode AS run_mode,
  h.task_type,
  h.resource_set_id,
  h.source_record_key,
  h.status,
  h.assigned_to_principal_type,
  h.assigned_to_principal_id,
  h.due_at,
  h.completed_at,
  h.created_at,
  h.updated_at
FROM flowforge_human_tasks h
LEFT JOIN flowforge_runs r
  ON r.workspace_id = h.workspace_id
 AND r.id = h.run_id
WHERE h.task_type = 'offer';

CREATE OR REPLACE VIEW v_flowforge_report_assignments AS
SELECT
  a.id,
  a.workspace_id,
  a.run_id,
  r.mode AS run_mode,
  a.human_task_id,
  a.resource_set_id,
  a.source_record_key,
  a.status,
  a.assigned_at,
  a.released_at
FROM flowforge_assignments a
LEFT JOIN flowforge_runs r
  ON r.workspace_id = a.workspace_id
 AND r.id = a.run_id;

CREATE OR REPLACE VIEW v_flowforge_report_notifications AS
SELECT
  n.id,
  n.workspace_id,
  n.run_id,
  r.mode AS run_mode,
  n.human_task_id,
  n.channel,
  n.template_key,
  n.status,
  n.created_at,
  n.sent_at,
  n.failed_at
FROM flowforge_notifications n
LEFT JOIN flowforge_runs r
  ON r.workspace_id = n.workspace_id
 AND r.id = n.run_id;
