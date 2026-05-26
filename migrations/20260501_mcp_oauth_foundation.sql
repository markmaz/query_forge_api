INSERT IGNORE INTO roles (name, display_name, description, feature_key, is_system)
VALUES
  (
    'queryforge_mcp:user',
    'QueryForge MCP User',
    'Allows a user to connect and use non-preview QueryForge MCP tools for an enabled workspace.',
    'queryforge_mcp',
    1
  ),
  (
    'queryforge_mcp:preview',
    'QueryForge MCP Preview',
    'Allows a user to preview governed query results through QueryForge MCP when normal Query Studio access also passes.',
    'queryforge_mcp',
    1
  ),
  (
    'queryforge_mcp:admin',
    'QueryForge MCP Admin',
    'Reserved for future MCP administration and diagnostics.',
    'queryforge_mcp',
    1
  );

CREATE TABLE IF NOT EXISTS workspace_mcp_settings (
  workspace_id VARCHAR(128) NOT NULL,
  enabled TINYINT(1) NOT NULL DEFAULT 0,
  enabled_by VARCHAR(255) NULL,
  enabled_at DATETIME NULL,
  disabled_by VARCHAR(255) NULL,
  disabled_at DATETIME NULL,
  default_preview_row_limit INT UNSIGNED NOT NULL DEFAULT 100,
  max_preview_row_limit INT UNSIGNED NOT NULL DEFAULT 500,
  block_sensitive_domains TINYINT(1) NOT NULL DEFAULT 0,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (workspace_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS oauth_clients (
  client_id VARCHAR(128) NOT NULL,
  client_secret_hash VARCHAR(255) NULL,
  client_name VARCHAR(255) NULL,
  redirect_uris JSON NOT NULL,
  grant_types JSON NULL,
  response_types JSON NULL,
  scope TEXT NULL,
  token_endpoint_auth_method VARCHAR(64) NULL,
  client_uri VARCHAR(1024) NULL,
  logo_uri VARCHAR(1024) NULL,
  contacts JSON NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  expires_at DATETIME NULL,
  revoked_at DATETIME NULL,
  PRIMARY KEY (client_id),
  KEY idx_oauth_clients_expires_at (expires_at),
  KEY idx_oauth_clients_revoked_at (revoked_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS oauth_authorization_codes (
  code_hash VARCHAR(64) NOT NULL,
  client_id VARCHAR(128) NOT NULL,
  principal_type VARCHAR(16) NOT NULL,
  principal_id VARCHAR(255) NOT NULL,
  redirect_uri VARCHAR(1024) NOT NULL,
  resource VARCHAR(512) NOT NULL,
  scope TEXT NULL,
  code_challenge VARCHAR(255) NOT NULL,
  code_challenge_method VARCHAR(32) NOT NULL,
  nonce VARCHAR(255) NULL,
  state_hash VARCHAR(64) NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  expires_at DATETIME NOT NULL,
  consumed_at DATETIME NULL,
  PRIMARY KEY (code_hash),
  KEY idx_oac_client (client_id),
  KEY idx_oac_principal (principal_type, principal_id),
  KEY idx_oac_expires_at (expires_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS oauth_refresh_tokens (
  token_hash VARCHAR(64) NOT NULL,
  client_id VARCHAR(128) NOT NULL,
  principal_type VARCHAR(16) NOT NULL,
  principal_id VARCHAR(255) NOT NULL,
  resource VARCHAR(512) NOT NULL,
  scope TEXT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  expires_at DATETIME NOT NULL,
  rotated_at DATETIME NULL,
  revoked_at DATETIME NULL,
  replaced_by_hash VARCHAR(64) NULL,
  PRIMARY KEY (token_hash),
  KEY idx_ort_client (client_id),
  KEY idx_ort_principal (principal_type, principal_id),
  KEY idx_ort_expires_at (expires_at),
  KEY idx_ort_revoked_at (revoked_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS mcp_principal_grants (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  principal_type VARCHAR(16) NOT NULL,
  principal_id VARCHAR(255) NOT NULL,
  workspace_id VARCHAR(128) NOT NULL,
  enabled TINYINT(1) NOT NULL DEFAULT 1,
  allowed_tools JSON NULL,
  allowed_domain_keys JSON NULL,
  can_preview TINYINT(1) NOT NULL DEFAULT 0,
  preview_row_limit INT UNSIGNED NOT NULL DEFAULT 100,
  created_by VARCHAR(255) NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  expires_at DATETIME NULL,
  revoked_at DATETIME NULL,
  PRIMARY KEY (id),
  CONSTRAINT uidx_mpg_principal_workspace UNIQUE (principal_type, principal_id, workspace_id),
  KEY idx_mpg_principal_workspace (principal_type, principal_id, workspace_id),
  KEY idx_mpg_workspace (workspace_id, enabled)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS oauth_consents (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  client_id VARCHAR(128) NOT NULL,
  principal_type VARCHAR(16) NOT NULL,
  principal_id VARCHAR(255) NOT NULL,
  resource VARCHAR(512) NOT NULL,
  scope TEXT NULL,
  granted_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  expires_at DATETIME NULL,
  revoked_at DATETIME NULL,
  PRIMARY KEY (id),
  KEY idx_oauth_consents_client_principal (client_id, principal_type, principal_id),
  KEY idx_oauth_consents_revoked_at (revoked_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS mcp_app_clients (
  client_id VARCHAR(128) NOT NULL,
  client_secret_hash VARCHAR(255) NOT NULL,
  display_name VARCHAR(255) NOT NULL,
  description TEXT NULL,
  owning_workspace_id VARCHAR(128) NOT NULL,
  owner_user_id VARCHAR(255) NULL,
  created_by VARCHAR(255) NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  last_used_at DATETIME NULL,
  expires_at DATETIME NULL,
  revoked_at DATETIME NULL,
  rotation_required_at DATETIME NULL,
  PRIMARY KEY (client_id),
  KEY idx_mac_workspace (owning_workspace_id),
  KEY idx_mac_revoked_at (revoked_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS mcp_oauth_audit_log (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  event_type VARCHAR(64) NOT NULL,
  principal_type VARCHAR(16) NULL,
  principal_id VARCHAR(255) NULL,
  client_id VARCHAR(128) NULL,
  workspace_id VARCHAR(128) NULL,
  requested_resource VARCHAR(512) NULL,
  requested_scopes TEXT NULL,
  tool_name VARCHAR(128) NULL,
  domain_key VARCHAR(255) NULL,
  saved_query_id VARCHAR(128) NULL,
  decision VARCHAR(32) NOT NULL,
  denial_reason VARCHAR(255) NULL,
  row_count_returned INT UNSIGNED NULL,
  rate_limit_bucket VARCHAR(128) NULL,
  trace_id VARCHAR(128) NULL,
  details_json JSON NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_mcp_audit_principal (principal_type, principal_id),
  KEY idx_mcp_audit_workspace (workspace_id),
  KEY idx_mcp_audit_event (event_type),
  KEY idx_mcp_audit_created (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
