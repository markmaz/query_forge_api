CREATE OR REPLACE VIEW v_flowforge_report_workflow_runs AS
SELECT
  r.id,
  r.id AS run_id,
  r.workspace_id,
  r.workflow_definition_id,
  r.workflow_version_id,
  d.workflow_key,
  d.name AS workflow_name,
  d.lifecycle AS workflow_lifecycle,
  r.intake_event_id,
  r.mode,
  r.status,
  r.current_node_id,
  COALESCE(r.run_as_principal_type, d.run_as_principal_type) AS run_as_principal_type,
  COALESCE(r.run_as_principal_id, d.run_as_principal_id) AS run_as_principal_id,
  r.triggered_by_user_id,
  r.started_at,
  r.completed_at,
  r.failed_at,
  CASE WHEN r.completed_at IS NOT NULL THEN TIMESTAMPDIFF(SECOND, r.started_at, r.completed_at) ELSE NULL END AS duration_seconds,
  CASE WHEN r.status = 'completed' THEN 1 ELSE 0 END AS completed_flag,
  CASE WHEN r.status = 'failed' THEN 1 ELSE 0 END AS failed_flag,
  CASE WHEN r.status = 'needs_attention' THEN 1 ELSE 0 END AS needs_attention_flag,
  r.created_at,
  r.updated_at
FROM flowforge_runs r
LEFT JOIN flowforge_workflow_definitions d
  ON d.workspace_id = r.workspace_id
 AND d.id = r.workflow_definition_id;

CREATE OR REPLACE VIEW v_flowforge_report_matching_evaluations AS
SELECT
  e.id,
  e.id AS matching_evaluation_id,
  e.workspace_id,
  e.run_id,
  r.mode AS run_mode,
  r.workflow_definition_id,
  r.workflow_version_id,
  d.workflow_key,
  d.name AS workflow_name,
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
 AND r.id = e.run_id
LEFT JOIN flowforge_workflow_definitions d
  ON d.workspace_id = r.workspace_id
 AND d.id = r.workflow_definition_id;

CREATE OR REPLACE VIEW v_flowforge_report_notifications AS
SELECT
  n.id,
  n.id AS notification_id,
  n.workspace_id,
  n.run_id,
  r.mode AS run_mode,
  r.workflow_definition_id,
  r.workflow_version_id,
  d.workflow_key,
  d.name AS workflow_name,
  n.human_task_id,
  n.channel,
  n.template_key,
  n.status,
  n.created_at,
  n.sent_at,
  n.failed_at,
  CASE
    WHEN n.sent_at IS NOT NULL THEN TIMESTAMPDIFF(SECOND, n.created_at, n.sent_at)
    WHEN n.failed_at IS NOT NULL THEN TIMESTAMPDIFF(SECOND, n.created_at, n.failed_at)
    ELSE NULL
  END AS delivery_latency_seconds
FROM flowforge_notifications n
LEFT JOIN flowforge_runs r
  ON r.workspace_id = n.workspace_id
 AND r.id = n.run_id
LEFT JOIN flowforge_workflow_definitions d
  ON d.workspace_id = r.workspace_id
 AND d.id = r.workflow_definition_id;

CREATE OR REPLACE VIEW v_flowforge_report_dataset_artifacts AS
SELECT
  a.id,
  a.id AS dataset_artifact_id,
  a.workspace_id,
  a.run_id,
  r.mode AS run_mode,
  r.workflow_definition_id,
  r.workflow_version_id,
  d.workflow_key,
  d.name AS workflow_name,
  a.node_id,
  a.artifact_key,
  a.artifact_type,
  a.storage_kind,
  a.row_count,
  a.byte_count,
  a.status,
  CASE
    WHEN a.expires_at IS NOT NULL AND a.expires_at < CURRENT_TIMESTAMP THEN 'expired'
    WHEN a.expires_at IS NOT NULL THEN 'retention_pending'
    ELSE 'no_expiry'
  END AS retention_state,
  a.expires_at,
  a.created_at,
  a.updated_at
FROM flowforge_dataset_artifacts a
LEFT JOIN flowforge_runs r
  ON r.workspace_id = a.workspace_id
 AND r.id = a.run_id
LEFT JOIN flowforge_workflow_definitions d
  ON d.workspace_id = r.workspace_id
 AND d.id = r.workflow_definition_id;

CREATE OR REPLACE VIEW v_flowforge_report_data_movement_audit AS
SELECT
  a.id,
  a.id AS data_movement_audit_id,
  a.workspace_id,
  a.run_id,
  r.mode AS run_mode,
  r.workflow_definition_id,
  r.workflow_version_id,
  d.workflow_key,
  d.name AS workflow_name,
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
  CASE WHEN a.completed_at IS NOT NULL THEN TIMESTAMPDIFF(SECOND, a.started_at, a.completed_at) ELSE NULL END AS action_duration_seconds,
  a.created_at
FROM flowforge_data_movement_audit a
LEFT JOIN flowforge_runs r
  ON r.workspace_id = a.workspace_id
 AND r.id = a.run_id
LEFT JOIN flowforge_workflow_definitions d
  ON d.workspace_id = r.workspace_id
 AND d.id = r.workflow_definition_id;

CREATE OR REPLACE VIEW v_flowforge_report_workflow_checkpoints AS
SELECT
  e.workspace_id,
  e.run_id,
  r.workflow_definition_id,
  r.workflow_version_id,
  d.workflow_key,
  d.name AS workflow_name,
  r.mode AS run_mode,
  e.id AS event_id,
  e.event_type,
  COALESCE(JSON_UNQUOTE(JSON_EXTRACT(e.event_payload_json, '$.checkpoint_key')), e.event_type) AS checkpoint_key,
  e.node_id,
  JSON_UNQUOTE(JSON_EXTRACT(e.event_payload_json, '$.node_type')) AS node_type,
  JSON_UNQUOTE(JSON_EXTRACT(e.event_payload_json, '$.node_label')) AS node_label,
  COALESCE(
    JSON_UNQUOTE(JSON_EXTRACT(e.event_payload_json, '$.checkpoint_status')),
    CASE
      WHEN e.event_type LIKE '%.failed' OR e.event_type LIKE '%failed%' THEN 'failed'
      WHEN e.event_type LIKE '%.completed' OR e.event_type LIKE '%completed%' THEN 'completed'
      WHEN e.event_type LIKE '%started%' THEN 'started'
      ELSE 'recorded'
    END
  ) AS checkpoint_status,
  e.message,
  e.actor_type,
  e.actor_id,
  e.created_at,
  TIMESTAMPDIFF(SECOND, r.started_at, e.created_at) AS seconds_since_run_start
FROM flowforge_run_events e
JOIN flowforge_runs r
  ON r.workspace_id = e.workspace_id
 AND r.id = e.run_id
LEFT JOIN flowforge_workflow_definitions d
  ON d.workspace_id = r.workspace_id
 AND d.id = r.workflow_definition_id;

CREATE OR REPLACE VIEW v_flowforge_report_matching_candidates AS
SELECT
  c.id,
  c.id AS candidate_id,
  c.workspace_id,
  c.matching_evaluation_id,
  e.run_id,
  r.mode AS run_mode,
  r.workflow_definition_id,
  r.workflow_version_id,
  d.workflow_key,
  d.name AS workflow_name,
  e.matching_policy_version_id,
  c.resource_set_id,
  e.snapshot_batch_id,
  c.source_record_key,
  rs.display_name AS resource_display_name,
  c.rank_position AS candidate_rank,
  c.score,
  c.selected,
  c.included,
  c.excluded,
  JSON_UNQUOTE(JSON_EXTRACT(c.eligibility_result_json, '$.reason')) AS exclusion_reason,
  e.evaluated_at,
  c.created_at
FROM flowforge_matching_evaluation_candidates c
JOIN flowforge_matching_evaluations e
  ON e.workspace_id = c.workspace_id
 AND e.id = c.matching_evaluation_id
LEFT JOIN flowforge_runs r
  ON r.workspace_id = e.workspace_id
 AND r.id = e.run_id
LEFT JOIN flowforge_workflow_definitions d
  ON d.workspace_id = r.workspace_id
 AND d.id = r.workflow_definition_id
LEFT JOIN flowforge_resource_snapshot_records rs
  ON rs.workspace_id = c.workspace_id
 AND rs.resource_set_id = c.resource_set_id
 AND rs.snapshot_batch_id = e.snapshot_batch_id
 AND rs.source_record_key = c.source_record_key;

CREATE OR REPLACE VIEW v_flowforge_report_offer_outcomes AS
SELECT
  h.workspace_id,
  h.run_id,
  r.workflow_definition_id,
  r.workflow_version_id,
  d.workflow_key,
  d.name AS workflow_name,
  r.mode AS run_mode,
  h.id AS human_task_id,
  h.resource_set_id,
  h.source_record_key,
  rs.display_name AS resource_display_name,
  h.status AS offer_status,
  CASE
    WHEN h.status IN ('accepted', 'approved') THEN 'accepted'
    WHEN h.status IN ('declined', 'rejected') THEN 'declined'
    WHEN h.status IN ('timed_out', 'timeout', 'expired') THEN 'timed_out'
    WHEN h.status IN ('pending', 'waiting') THEN 'pending'
    WHEN h.status = 'cancelled' THEN 'cancelled'
    ELSE h.status
  END AS outcome,
  h.assigned_to_principal_type,
  h.assigned_to_principal_id,
  h.created_at AS offered_at,
  h.due_at,
  h.completed_at,
  CASE WHEN h.completed_at IS NOT NULL THEN TIMESTAMPDIFF(SECOND, h.created_at, h.completed_at) ELSE NULL END AS response_seconds,
  a.id AS assignment_id,
  a.status AS assignment_status,
  a.assigned_at
FROM flowforge_human_tasks h
LEFT JOIN flowforge_runs r
  ON r.workspace_id = h.workspace_id
 AND r.id = h.run_id
LEFT JOIN flowforge_workflow_definitions d
  ON d.workspace_id = r.workspace_id
 AND d.id = r.workflow_definition_id
LEFT JOIN flowforge_assignments a
  ON a.workspace_id = h.workspace_id
 AND a.human_task_id = h.id
LEFT JOIN flowforge_resource_snapshot_records rs
  ON rs.workspace_id = h.workspace_id
 AND rs.resource_set_id = h.resource_set_id
 AND rs.source_record_key = h.source_record_key
 AND rs.id = (
    SELECT MAX(rs_latest.id)
    FROM flowforge_resource_snapshot_records rs_latest
    WHERE rs_latest.workspace_id = h.workspace_id
      AND rs_latest.resource_set_id = h.resource_set_id
      AND rs_latest.source_record_key = h.source_record_key
  )
WHERE h.task_type = 'offer';

CREATE OR REPLACE VIEW v_flowforge_report_assignment_funnel AS
SELECT
  r.workspace_id,
  r.id AS run_id,
  r.workflow_definition_id,
  r.workflow_version_id,
  d.workflow_key,
  d.name AS workflow_name,
  r.mode AS run_mode,
  ie.received_at AS intake_received_at,
  me.matching_evaluated_at,
  ht.first_offer_created_at,
  ht.first_response_at,
  a.assigned_at,
  r.completed_at,
  me.no_match_reason,
  CASE
    WHEN a.assigned_at IS NOT NULL THEN 'assigned'
    WHEN me.no_match_reason IS NOT NULL THEN 'no_match'
    WHEN r.status IN ('failed', 'needs_attention') THEN r.status
    WHEN ht.offer_attempt_count > 0 THEN 'offer_pending'
    WHEN me.matching_evaluated_at IS NOT NULL THEN 'matched'
    ELSE r.status
  END AS funnel_status,
  CASE WHEN ht.first_offer_created_at IS NOT NULL THEN TIMESTAMPDIFF(SECOND, r.started_at, ht.first_offer_created_at) ELSE NULL END AS time_to_first_offer_seconds,
  CASE WHEN a.assigned_at IS NOT NULL THEN TIMESTAMPDIFF(SECOND, r.started_at, a.assigned_at) ELSE NULL END AS time_to_assignment_seconds,
  COALESCE(ht.offer_attempt_count, 0) AS offer_attempt_count,
  COALESCE(ht.decline_count, 0) AS decline_count,
  COALESCE(ht.timeout_count, 0) AS timeout_count
FROM flowforge_runs r
LEFT JOIN flowforge_workflow_definitions d
  ON d.workspace_id = r.workspace_id
 AND d.id = r.workflow_definition_id
LEFT JOIN flowforge_intake_events ie
  ON ie.workspace_id = r.workspace_id
 AND ie.id = r.intake_event_id
LEFT JOIN (
  SELECT
    workspace_id,
    run_id,
    MIN(evaluated_at) AS matching_evaluated_at,
    MAX(no_match_reason) AS no_match_reason
  FROM flowforge_matching_evaluations
  GROUP BY workspace_id, run_id
) me
  ON me.workspace_id = r.workspace_id
 AND me.run_id = r.id
LEFT JOIN (
  SELECT
    workspace_id,
    run_id,
    MIN(created_at) AS first_offer_created_at,
    MIN(completed_at) AS first_response_at,
    COUNT(*) AS offer_attempt_count,
    SUM(CASE WHEN status IN ('declined', 'rejected') THEN 1 ELSE 0 END) AS decline_count,
    SUM(CASE WHEN status IN ('timed_out', 'timeout', 'expired') THEN 1 ELSE 0 END) AS timeout_count
  FROM flowforge_human_tasks
  WHERE task_type = 'offer'
  GROUP BY workspace_id, run_id
) ht
  ON ht.workspace_id = r.workspace_id
 AND ht.run_id = r.id
LEFT JOIN (
  SELECT
    workspace_id,
    run_id,
    MIN(assigned_at) AS assigned_at
  FROM flowforge_assignments
  GROUP BY workspace_id, run_id
) a
  ON a.workspace_id = r.workspace_id
 AND a.run_id = r.id;
