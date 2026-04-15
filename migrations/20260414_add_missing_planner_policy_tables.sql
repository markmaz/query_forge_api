CREATE TABLE IF NOT EXISTS planner_projection_policy (
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
  UNIQUE KEY uidx_projection_policy_scope (
    policy_key,
    scope_workspace_id,
    scope_vertical_norm,
    scope_base_domain_id
  ),
  KEY idx_ppp_scope (scope_workspace_id, scope_vertical_norm, scope_base_domain_id),
  KEY idx_ppp_priority (priority),
  KEY idx_ppp_active (is_active)
);

CREATE TABLE IF NOT EXISTS planner_signal_policy (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  policy_key VARCHAR(150) NOT NULL,
  name VARCHAR(255) NOT NULL,
  description TEXT NULL,
  scope_type VARCHAR(32) NOT NULL,
  scope_workspace_id VARCHAR(128) NULL,
  scope_vertical_norm VARCHAR(64) NULL,
  priority INT NOT NULL DEFAULT 100,
  is_active TINYINT(1) NOT NULL DEFAULT 1,
  stop_on_match TINYINT(1) NOT NULL DEFAULT 0,
  policy_json JSON NOT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uidx_signal_policy_scope (
    policy_key,
    scope_workspace_id,
    scope_vertical_norm
  ),
  KEY idx_psp_scope (scope_workspace_id, scope_vertical_norm),
  KEY idx_psp_priority (priority),
  KEY idx_psp_active (is_active)
);

CREATE TABLE IF NOT EXISTS planner_prompt_intent_policy (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  policy_key VARCHAR(150) NOT NULL,
  name VARCHAR(255) NOT NULL,
  description TEXT NULL,
  scope_type VARCHAR(32) NOT NULL,
  scope_workspace_id VARCHAR(128) NULL,
  scope_vertical_norm VARCHAR(64) NULL,
  priority INT NOT NULL DEFAULT 100,
  is_active TINYINT(1) NOT NULL DEFAULT 1,
  stop_on_match TINYINT(1) NOT NULL DEFAULT 0,
  policy_json JSON NOT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uidx_prompt_intent_policy_scope (
    policy_key,
    scope_workspace_id,
    scope_vertical_norm
  ),
  KEY idx_ppip_scope (scope_workspace_id, scope_vertical_norm),
  KEY idx_ppip_priority (priority),
  KEY idx_ppip_active (is_active)
);

CREATE TABLE IF NOT EXISTS planner_retrieval_policy (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  policy_key VARCHAR(150) NOT NULL,
  name VARCHAR(255) NOT NULL,
  description TEXT NULL,
  scope_type VARCHAR(32) NOT NULL,
  scope_workspace_id VARCHAR(128) NULL,
  scope_vertical_norm VARCHAR(64) NULL,
  priority INT NOT NULL DEFAULT 100,
  is_active TINYINT(1) NOT NULL DEFAULT 1,
  stop_on_match TINYINT(1) NOT NULL DEFAULT 0,
  policy_json JSON NOT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uidx_retrieval_policy_scope (
    policy_key,
    scope_workspace_id,
    scope_vertical_norm
  ),
  KEY idx_prp_scope (scope_workspace_id, scope_vertical_norm),
  KEY idx_prp_priority (priority),
  KEY idx_prp_active (is_active)
);

CREATE TABLE IF NOT EXISTS planner_domain_selection_policy (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  policy_key VARCHAR(150) NOT NULL,
  name VARCHAR(255) NOT NULL,
  description TEXT NULL,
  scope_type VARCHAR(32) NOT NULL,
  scope_workspace_id VARCHAR(128) NULL,
  scope_vertical_norm VARCHAR(64) NULL,
  priority INT NOT NULL DEFAULT 100,
  is_active TINYINT(1) NOT NULL DEFAULT 1,
  stop_on_match TINYINT(1) NOT NULL DEFAULT 0,
  policy_json JSON NOT NULL,
  score_delta DECIMAL(6,4) NOT NULL DEFAULT 0.0,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uidx_domain_selection_policy_scope (
    policy_key,
    scope_workspace_id,
    scope_vertical_norm
  ),
  KEY idx_pdsp_scope (scope_workspace_id, scope_vertical_norm),
  KEY idx_pdsp_priority (priority),
  KEY idx_pdsp_active (is_active)
);

CREATE TABLE IF NOT EXISTS planner_capability_packing_policy (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  policy_key VARCHAR(150) NOT NULL,
  name VARCHAR(255) NOT NULL,
  description TEXT NULL,
  scope_type VARCHAR(32) NOT NULL,
  scope_workspace_id VARCHAR(128) NULL,
  scope_vertical_norm VARCHAR(64) NULL,
  priority INT NOT NULL DEFAULT 100,
  is_active TINYINT(1) NOT NULL DEFAULT 1,
  stop_on_match TINYINT(1) NOT NULL DEFAULT 0,
  policy_json JSON NOT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uidx_capability_packing_policy_scope (
    policy_key,
    scope_workspace_id,
    scope_vertical_norm
  ),
  KEY idx_pcpp_scope (scope_workspace_id, scope_vertical_norm),
  KEY idx_pcpp_priority (priority),
  KEY idx_pcpp_active (is_active)
);

CREATE TABLE IF NOT EXISTS planner_concept_scoring_policy (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  policy_key VARCHAR(150) NOT NULL,
  name VARCHAR(255) NOT NULL,
  description TEXT NULL,
  scope_type VARCHAR(32) NOT NULL,
  scope_workspace_id VARCHAR(128) NULL,
  scope_vertical_norm VARCHAR(64) NULL,
  priority INT NOT NULL DEFAULT 100,
  is_active TINYINT(1) NOT NULL DEFAULT 1,
  stop_on_match TINYINT(1) NOT NULL DEFAULT 0,
  policy_json JSON NOT NULL,
  factor_value DECIMAL(6,4) NULL,
  penalty_value DECIMAL(6,4) NULL,
  integer_value INT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uidx_concept_scoring_policy_scope (
    policy_key,
    scope_workspace_id,
    scope_vertical_norm
  ),
  KEY idx_pcsp_scope (scope_workspace_id, scope_vertical_norm),
  KEY idx_pcsp_priority (priority),
  KEY idx_pcsp_active (is_active)
);

CREATE TABLE IF NOT EXISTS planner_semantic_join_policy (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  policy_key VARCHAR(150) NOT NULL,
  name VARCHAR(255) NOT NULL,
  description TEXT NULL,
  scope_type VARCHAR(32) NOT NULL,
  scope_workspace_id VARCHAR(128) NULL,
  scope_vertical_norm VARCHAR(64) NULL,
  priority INT NOT NULL DEFAULT 100,
  is_active TINYINT(1) NOT NULL DEFAULT 1,
  stop_on_match TINYINT(1) NOT NULL DEFAULT 0,
  policy_json JSON NOT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uidx_semantic_join_policy_scope (
    policy_key,
    scope_workspace_id,
    scope_vertical_norm
  ),
  KEY idx_psjp_scope (scope_workspace_id, scope_vertical_norm),
  KEY idx_psjp_priority (priority),
  KEY idx_psjp_active (is_active)
);

CREATE TABLE IF NOT EXISTS planner_semantic_projection_policy (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  policy_key VARCHAR(150) NOT NULL,
  name VARCHAR(255) NOT NULL,
  description TEXT NULL,
  scope_type VARCHAR(32) NOT NULL,
  scope_workspace_id VARCHAR(128) NULL,
  scope_vertical_norm VARCHAR(64) NULL,
  priority INT NOT NULL DEFAULT 100,
  is_active TINYINT(1) NOT NULL DEFAULT 1,
  stop_on_match TINYINT(1) NOT NULL DEFAULT 0,
  policy_json JSON NOT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uidx_semantic_projection_policy_scope (
    policy_key,
    scope_workspace_id,
    scope_vertical_norm
  ),
  KEY idx_pspp_scope (scope_workspace_id, scope_vertical_norm),
  KEY idx_pspp_priority (priority),
  KEY idx_pspp_active (is_active)
);

CREATE TABLE IF NOT EXISTS planner_semantic_time_policy (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  policy_key VARCHAR(150) NOT NULL,
  name VARCHAR(255) NOT NULL,
  description TEXT NULL,
  scope_type VARCHAR(32) NOT NULL,
  scope_workspace_id VARCHAR(128) NULL,
  scope_vertical_norm VARCHAR(64) NULL,
  priority INT NOT NULL DEFAULT 100,
  is_active TINYINT(1) NOT NULL DEFAULT 1,
  stop_on_match TINYINT(1) NOT NULL DEFAULT 0,
  policy_json JSON NOT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uidx_semantic_time_policy_scope (
    policy_key,
    scope_workspace_id,
    scope_vertical_norm
  ),
  KEY idx_pstp_scope (scope_workspace_id, scope_vertical_norm),
  KEY idx_pstp_priority (priority),
  KEY idx_pstp_active (is_active)
);
