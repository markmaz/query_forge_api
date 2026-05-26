CREATE TABLE IF NOT EXISTS prompt_failure_analysis (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  prompt_feedback_id BIGINT UNSIGNED NOT NULL,
  evaluator_model VARCHAR(128) NULL,
  evaluator_version VARCHAR(64) NULL,
  status VARCHAR(32) NOT NULL DEFAULT 'pending',
  failure_verdict VARCHAR(64) NULL,
  confidence DECIMAL(4,3) NULL,
  analysis_json JSON NULL,
  raw_llm_output TEXT NULL,
  error_message TEXT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  CONSTRAINT uidx_pfa_prompt_feedback_id UNIQUE (prompt_feedback_id),
  KEY idx_pfa_status (status),
  CONSTRAINT fk_pfa_prompt_feedback_id
    FOREIGN KEY (prompt_feedback_id) REFERENCES prompt_feedback(id)
    ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS semantic_update_candidate (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  failure_analysis_id BIGINT UNSIGNED NOT NULL,
  target_type VARCHAR(64) NOT NULL,
  concept_key VARCHAR(255) NULL,
  domain_key VARCHAR(255) NULL,
  change_type VARCHAR(64) NOT NULL,
  payload_json JSON NOT NULL,
  payload_hash VARCHAR(64) NOT NULL,
  risk_level VARCHAR(32) NOT NULL,
  evidence_count INT UNSIGNED NOT NULL DEFAULT 1,
  confidence DECIMAL(4,3) NOT NULL,
  governance_status VARCHAR(32) NOT NULL DEFAULT 'pending',
  auto_apply_eligible TINYINT(1) NOT NULL DEFAULT 0,
  source_scope VARCHAR(32) NOT NULL DEFAULT 'global',
  workspace_id VARCHAR(64) NULL,
  workspace_scope_key VARCHAR(80) NOT NULL,
  reviewed_by VARCHAR(255) NULL,
  reviewed_at DATETIME NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  CONSTRAINT uidx_suc_hash_scope UNIQUE (payload_hash, source_scope, workspace_scope_key),
  KEY idx_suc_governance_status (governance_status),
  KEY idx_suc_workspace_id (workspace_id),
  KEY idx_suc_concept_key (concept_key),
  KEY idx_suc_domain_key (domain_key),
  CONSTRAINT fk_suc_failure_analysis_id
    FOREIGN KEY (failure_analysis_id) REFERENCES prompt_failure_analysis(id)
    ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS semantic_override (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  workspace_id VARCHAR(64) NULL,
  concept_key VARCHAR(255) NOT NULL,
  override_type VARCHAR(64) NOT NULL,
  override_key VARCHAR(255) NOT NULL,
  override_value_json JSON NOT NULL,
  source_candidate_id BIGINT UNSIGNED NULL,
  status VARCHAR(32) NOT NULL DEFAULT 'active',
  approved_by VARCHAR(255) NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_so_concept_key (concept_key),
  KEY idx_so_workspace_status (workspace_id, status),
  CONSTRAINT fk_so_source_candidate_id
    FOREIGN KEY (source_candidate_id) REFERENCES semantic_update_candidate(id)
    ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS domain_override (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  workspace_id VARCHAR(64) NULL,
  domain_key VARCHAR(255) NOT NULL,
  override_type VARCHAR(64) NOT NULL,
  override_key VARCHAR(255) NOT NULL,
  override_value_json JSON NOT NULL,
  source_candidate_id BIGINT UNSIGNED NULL,
  status VARCHAR(32) NOT NULL DEFAULT 'active',
  approved_by VARCHAR(255) NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_do_domain_key (domain_key),
  KEY idx_do_workspace_status (workspace_id, status),
  CONSTRAINT fk_do_source_candidate_id
    FOREIGN KEY (source_candidate_id) REFERENCES semantic_update_candidate(id)
    ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS catalog_promotion_audit (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  source_type VARCHAR(64) NOT NULL,
  source_id BIGINT UNSIGNED NOT NULL,
  target_table VARCHAR(128) NOT NULL,
  target_record_key VARCHAR(255) NOT NULL,
  promotion_action VARCHAR(64) NOT NULL,
  promotion_status VARCHAR(32) NOT NULL,
  promoted_by VARCHAR(255) NOT NULL,
  promoted_at DATETIME NOT NULL,
  retry_count INT UNSIGNED NOT NULL DEFAULT 0,
  last_retry_at DATETIME NULL,
  notes TEXT NULL,
  error_message TEXT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_cpa_source (source_type, source_id),
  KEY idx_cpa_status (promotion_status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
