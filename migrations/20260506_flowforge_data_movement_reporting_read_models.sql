CREATE OR REPLACE VIEW v_flowforge_report_dataset_artifacts AS
SELECT
  a.id,
  a.workspace_id,
  a.run_id,
  r.mode AS run_mode,
  a.node_id,
  a.artifact_key,
  a.artifact_type,
  a.storage_kind,
  a.row_count,
  a.byte_count,
  a.status,
  a.expires_at,
  a.created_at,
  a.updated_at
FROM flowforge_dataset_artifacts a
LEFT JOIN flowforge_runs r
  ON r.workspace_id = a.workspace_id
 AND r.id = a.run_id;

CREATE OR REPLACE VIEW v_flowforge_report_data_movement_audit AS
SELECT
  a.id,
  a.workspace_id,
  a.run_id,
  r.mode AS run_mode,
  a.node_id,
  a.action_type,
  a.status,
  a.source_key,
  a.destination_key,
  a.dataset_artifact_id,
  a.resource_set_id,
  a.actor_type,
  a.actor_id,
  a.error_message,
  a.started_at,
  a.completed_at,
  a.created_at
FROM flowforge_data_movement_audit a
LEFT JOIN flowforge_runs r
  ON r.workspace_id = a.workspace_id
 AND r.id = a.run_id;
