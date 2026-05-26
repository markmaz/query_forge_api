CREATE TABLE IF NOT EXISTS flowforge_workspace_settings (
  workspace_id VARCHAR(128) NOT NULL,
  enabled TINYINT(1) NOT NULL DEFAULT 0,
  allow_designer_publish TINYINT(1) NOT NULL DEFAULT 0,
  raw_payload_retention_days SMALLINT UNSIGNED NOT NULL DEFAULT 30,
  raw_payload_retention_max_days SMALLINT UNSIGNED NOT NULL DEFAULT 90,
  default_offer_timeout_minutes INT UNSIGNED NOT NULL DEFAULT 1440,
  default_no_match_recipients_json JSON NULL,
  default_test_recipients_json JSON NULL,
  settings_json JSON NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (workspace_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS flowforge_workflow_definitions (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  workspace_id VARCHAR(128) NOT NULL,
  workflow_key VARCHAR(128) NOT NULL,
  name VARCHAR(255) NOT NULL,
  description TEXT NULL,
  status VARCHAR(32) NOT NULL DEFAULT 'draft',
  current_draft_version_id BIGINT UNSIGNED NULL,
  latest_published_version_id BIGINT UNSIGNED NULL,
  created_by VARCHAR(255) NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_by VARCHAR(255) NULL,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  archived_by VARCHAR(255) NULL,
  archived_at DATETIME NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uidx_ff_workflow_key (workspace_id, workflow_key),
  KEY idx_ff_workflow_workspace_status (workspace_id, status),
  KEY idx_ff_workflow_archived (workspace_id, archived_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS flowforge_workflow_versions (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  workspace_id VARCHAR(128) NOT NULL,
  workflow_definition_id BIGINT UNSIGNED NOT NULL,
  version_number INT UNSIGNED NOT NULL,
  version_status VARCHAR(32) NOT NULL DEFAULT 'draft',
  graph_json JSON NOT NULL,
  validation_status VARCHAR(32) NOT NULL DEFAULT 'pending',
  validation_result_json JSON NULL,
  matching_policy_refs_json JSON NULL,
  settings_json JSON NULL,
  created_by VARCHAR(255) NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  published_by VARCHAR(255) NULL,
  published_at DATETIME NULL,
  archived_at DATETIME NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uidx_ff_workflow_version (workflow_definition_id, version_number),
  KEY idx_ff_workflow_version_workspace (workspace_id, workflow_definition_id),
  KEY idx_ff_workflow_version_status (workspace_id, version_status),
  KEY idx_ff_workflow_version_published (workspace_id, published_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
