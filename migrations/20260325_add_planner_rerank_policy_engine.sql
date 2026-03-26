CREATE TABLE IF NOT EXISTS planner_domain_capability (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  scope_type VARCHAR(32) NOT NULL,
  scope_workspace_id VARCHAR(128) NULL,
  scope_vertical_norm VARCHAR(64) NULL,
  base_domain_id BIGINT UNSIGNED NOT NULL,
  capability_key VARCHAR(100) NOT NULL,
  support_level VARCHAR(32) NOT NULL DEFAULT 'direct',
  source_type VARCHAR(32) NOT NULL DEFAULT 'semantic_concept',
  source_ref VARCHAR(255) NULL,
  confidence DECIMAL(5,4) NOT NULL DEFAULT 1.0000,
  notes TEXT NULL,
  is_active TINYINT(1) NOT NULL DEFAULT 1,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uidx_domain_capability_scope (
    base_domain_id,
    capability_key,
    scope_workspace_id,
    scope_vertical_norm,
    source_ref
  ),
  KEY idx_pdc_domain (base_domain_id),
  KEY idx_pdc_capability (capability_key),
  KEY idx_pdc_scope (scope_workspace_id, scope_vertical_norm)
);

CREATE TABLE IF NOT EXISTS planner_rerank_policy (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  policy_key VARCHAR(150) NOT NULL,
  name VARCHAR(255) NOT NULL,
  description TEXT NULL,
  scope_type VARCHAR(32) NOT NULL,
  scope_workspace_id VARCHAR(128) NULL,
  scope_vertical_norm VARCHAR(64) NULL,
  scope_base_domain_id BIGINT UNSIGNED NULL,
  priority INT NOT NULL DEFAULT 100,
  is_active TINYINT(1) NOT NULL DEFAULT 1,
  stop_on_match TINYINT(1) NOT NULL DEFAULT 0,
  policy_json JSON NOT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uidx_rerank_policy_scope (
    policy_key,
    scope_workspace_id,
    scope_vertical_norm,
    scope_base_domain_id
  ),
  KEY idx_prp_scope (scope_workspace_id, scope_vertical_norm, scope_base_domain_id),
  KEY idx_prp_priority (priority),
  KEY idx_prp_active (is_active)
);

CREATE TABLE IF NOT EXISTS planner_rerank_policy_audit (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  policy_id BIGINT UNSIGNED NOT NULL,
  action_type VARCHAR(50) NOT NULL,
  previous_policy_json JSON NULL,
  new_policy_json JSON NULL,
  actor_user_id VARCHAR(255) NULL,
  notes TEXT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  KEY idx_prpa_policy (policy_id),
  KEY idx_prpa_actor (actor_user_id)
);

CREATE TABLE IF NOT EXISTS planner_rerank_policy_candidate (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  candidate_key VARCHAR(150) NOT NULL,
  source_type VARCHAR(50) NOT NULL,
  workspace_id VARCHAR(128) NULL,
  vertical_norm VARCHAR(64) NULL,
  candidate_json JSON NOT NULL,
  rationale_json JSON NULL,
  confidence DECIMAL(5,4) NULL,
  review_status VARCHAR(32) NOT NULL DEFAULT 'pending',
  approved_policy_id BIGINT UNSIGNED NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  KEY idx_prpc_status (review_status),
  KEY idx_prpc_scope (workspace_id, vertical_norm)
);
