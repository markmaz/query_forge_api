CREATE TABLE IF NOT EXISTS workboard.custom_regions_lists (
  workspace_id VARCHAR(64) NOT NULL,
  list_name VARCHAR(255) NOT NULL,
  user_name VARCHAR(255) NULL,
  user_id VARCHAR(255) NULL,
  is_shared TINYINT(1) NOT NULL DEFAULT 0,
  create_date DATE NULL,
  expiration_date DATE NULL,
  zipcode VARCHAR(32) NOT NULL,
  subregion VARCHAR(255) NULL,
  region VARCHAR(255) NULL,

  PRIMARY KEY (workspace_id, list_name, zipcode),
  INDEX idx_regions_ws (workspace_id),
  INDEX idx_regions_ws_list (workspace_id, list_name),
  INDEX idx_regions_ws_user (workspace_id, user_id),
  INDEX idx_regions_ws_shared (workspace_id, is_shared)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS workboard.custom_npi_categories_lists (
  workspace_id VARCHAR(64) NOT NULL,
  list_name VARCHAR(255) NOT NULL,
  user_name VARCHAR(255) NULL,
  user_id VARCHAR(255) NULL,
  is_shared TINYINT(1) NOT NULL DEFAULT 0,
  create_date DATE NULL,
  expiration_date DATE NULL,
  npi_type_code VARCHAR(8) NULL,
  npi VARCHAR(32) NOT NULL,
  customer_npi_category_1 VARCHAR(255) NULL,
  customer_npi_category_2 VARCHAR(255) NULL,

  PRIMARY KEY (workspace_id, list_name, npi),
  INDEX idx_npi_ws (workspace_id),
  INDEX idx_npi_ws_list (workspace_id, list_name),
  INDEX idx_npi_ws_user (workspace_id, user_id),
  INDEX idx_npi_ws_shared (workspace_id, is_shared)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS workboard.custom_service_lines_lists (
  workspace_id VARCHAR(64) NOT NULL,
  list_name VARCHAR(255) NOT NULL,
  user_name VARCHAR(255) NULL,
  user_id VARCHAR(255) NULL,
  is_shared TINYINT(1) NOT NULL DEFAULT 0,
  create_date DATE NULL,
  expiration_date DATE NULL,
  procedure_code VARCHAR(64) NOT NULL,
  customer_service_line VARCHAR(255) NULL,
  customer_sub_service_line VARCHAR(255) NULL,

  PRIMARY KEY (workspace_id, list_name, procedure_code),
  INDEX idx_svc_ws (workspace_id),
  INDEX idx_svc_ws_list (workspace_id, list_name),
  INDEX idx_svc_ws_user (workspace_id, user_id),
  INDEX idx_svc_ws_shared (workspace_id, is_shared)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


CREATE TABLE IF NOT EXISTS crosswalk_list_meta (
  id CHAR(36) NOT NULL,
  workspace_id VARCHAR(64) NOT NULL,
  list_type VARCHAR(32) NOT NULL,
  list_id CHAR(36) NOT NULL,
  list_name VARCHAR(255) NOT NULL,
  user_id VARCHAR(255) NULL,
  user_name VARCHAR(255) NULL,
  is_shared TINYINT(1) NOT NULL DEFAULT 0,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

  PRIMARY KEY (id),
  UNIQUE KEY uq_cwlm_ws_type_listid (workspace_id, list_type, list_id),

  KEY ix_cwlm_ws_type (workspace_id, list_type),
  KEY ix_cwlm_ws_shared (workspace_id, is_shared),
  KEY ix_cwlm_ws_user (workspace_id, user_id)
);