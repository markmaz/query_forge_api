ALTER TABLE flowforge_workflow_definitions
  ADD COLUMN owner_user_id VARCHAR(255) NULL AFTER description,
  ADD COLUMN run_as_principal_type VARCHAR(32) NULL AFTER owner_user_id,
  ADD COLUMN run_as_principal_id VARCHAR(255) NULL AFTER run_as_principal_type,
  ADD COLUMN lifecycle VARCHAR(32) NOT NULL DEFAULT 'development' AFTER run_as_principal_id,
  ADD KEY idx_ff_workflow_owner (workspace_id, owner_user_id),
  ADD KEY idx_ff_workflow_run_as (workspace_id, run_as_principal_type, run_as_principal_id),
  ADD KEY idx_ff_workflow_lifecycle (workspace_id, lifecycle, status);

UPDATE flowforge_workflow_definitions
SET owner_user_id = COALESCE(owner_user_id, created_by),
    run_as_principal_type = COALESCE(run_as_principal_type, CASE WHEN created_by IS NULL THEN NULL ELSE 'user' END),
    run_as_principal_id = COALESCE(run_as_principal_id, created_by),
    lifecycle = COALESCE(NULLIF(lifecycle, ''), 'development')
WHERE archived_at IS NULL;

CREATE TABLE IF NOT EXISTS flowforge_workflow_acl (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  workspace_id VARCHAR(128) NOT NULL,
  workflow_definition_id BIGINT UNSIGNED NOT NULL,
  principal_type VARCHAR(32) NOT NULL,
  principal_id VARCHAR(255) NOT NULL,
  permission VARCHAR(32) NOT NULL,
  granted_by VARCHAR(255) NULL,
  granted_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  revoked_by VARCHAR(255) NULL,
  revoked_at DATETIME NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uidx_ff_workflow_acl_principal (workspace_id, workflow_definition_id, principal_type, principal_id),
  KEY idx_ff_workflow_acl_workflow (workspace_id, workflow_definition_id, revoked_at),
  KEY idx_ff_workflow_acl_principal (workspace_id, principal_type, principal_id, revoked_at),
  KEY idx_ff_workflow_acl_permission (workspace_id, permission, revoked_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT INTO flowforge_workflow_acl (
  workspace_id,
  workflow_definition_id,
  principal_type,
  principal_id,
  permission,
  granted_by
)
SELECT
  workspace_id,
  id,
  'user',
  owner_user_id,
  'owner',
  created_by
FROM flowforge_workflow_definitions
WHERE owner_user_id IS NOT NULL
  AND archived_at IS NULL
ON DUPLICATE KEY UPDATE
  permission = VALUES(permission),
  granted_by = VALUES(granted_by),
  revoked_by = NULL,
  revoked_at = NULL;

ALTER TABLE flowforge_runs
  ADD COLUMN run_as_principal_type VARCHAR(32) NULL AFTER mode,
  ADD COLUMN run_as_principal_id VARCHAR(255) NULL AFTER run_as_principal_type,
  ADD COLUMN triggered_by_user_id VARCHAR(255) NULL AFTER run_as_principal_id,
  ADD KEY idx_ff_run_run_as (workspace_id, run_as_principal_type, run_as_principal_id),
  ADD KEY idx_ff_run_triggered_by (workspace_id, triggered_by_user_id);
