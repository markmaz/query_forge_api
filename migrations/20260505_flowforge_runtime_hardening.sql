ALTER TABLE flowforge_human_tasks
  ADD COLUMN idempotency_key VARCHAR(255) NULL AFTER response_json,
  ADD UNIQUE KEY uidx_ff_human_task_idempotency (workspace_id, idempotency_key);

CREATE TABLE IF NOT EXISTS flowforge_assignments (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  workspace_id VARCHAR(128) NOT NULL,
  run_id BIGINT UNSIGNED NOT NULL,
  human_task_id BIGINT UNSIGNED NULL,
  resource_set_id BIGINT UNSIGNED NOT NULL,
  source_record_key VARCHAR(255) NOT NULL,
  status VARCHAR(32) NOT NULL DEFAULT 'assigned',
  assignment_json JSON NULL,
  assigned_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  released_at DATETIME NULL,
  idempotency_key VARCHAR(255) NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uidx_ff_assignment_idempotency (workspace_id, idempotency_key),
  KEY idx_ff_assignment_run (workspace_id, run_id),
  KEY idx_ff_assignment_resource (workspace_id, resource_set_id, source_record_key),
  KEY idx_ff_assignment_status (workspace_id, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
