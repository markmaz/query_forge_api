CREATE TABLE IF NOT EXISTS forge_match_session (
  id char(36) NOT NULL,
  workspace_id varchar(128) NOT NULL,
  uploaded_filename varchar(512) NOT NULL,
  file_type varchar(16) NOT NULL,
  created_by varchar(255) NOT NULL,
  status varchar(32) NOT NULL DEFAULT 'uploaded',
  sheet_count int NOT NULL DEFAULT 0,
  source_record_count int NOT NULL DEFAULT 0,
  analysis_started_at datetime DEFAULT NULL,
  analysis_completed_at datetime DEFAULT NULL,
  summary_json json DEFAULT NULL,
  created_at timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at timestamp NULL DEFAULT NULL ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_forge_match_session_workspace_created (workspace_id, created_at),
  KEY idx_forge_match_session_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS forge_match_source_record (
  id bigint unsigned NOT NULL AUTO_INCREMENT,
  session_id char(36) NOT NULL,
  row_id varchar(128) NOT NULL,
  sheet_name varchar(255) DEFAULT NULL,
  `row_number` int DEFAULT NULL,
  source_field_name varchar(255) NOT NULL,
  source_description text,
  source_type varchar(100) DEFAULT NULL,
  source_object_name varchar(255) DEFAULT NULL,
  sample_value text,
  category varchar(255) DEFAULT NULL,
  normalized_search_text text,
  raw_row_json json DEFAULT NULL,
  created_at timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_forge_match_source_session_row (session_id, row_id),
  KEY idx_forge_match_source_session_name (session_id, source_field_name),
  CONSTRAINT fk_forge_match_source_session
    FOREIGN KEY (session_id) REFERENCES forge_match_session (id)
    ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS forge_match_result (
  id char(36) NOT NULL,
  session_id char(36) NOT NULL,
  source_record_id bigint unsigned NOT NULL,
  best_match_workspace_column_id bigint unsigned DEFAULT NULL,
  alternate_workspace_column_ids json DEFAULT NULL,
  retrieved_candidates_json json DEFAULT NULL,
  llm_response_json json DEFAULT NULL,
  match_decision varchar(32) NOT NULL DEFAULT 'no_confident_match',
  reason_codes_json json DEFAULT NULL,
  explanation text,
  ambiguity_note text,
  llm_confidence decimal(5,4) DEFAULT NULL,
  confidence_score int NOT NULL DEFAULT 0,
  confidence_band varchar(16) NOT NULL DEFAULT 'low',
  status varchar(32) NOT NULL DEFAULT 'suggested',
  review_notes text,
  manually_selected_workspace_column_id bigint unsigned DEFAULT NULL,
  reviewer_user_id varchar(255) DEFAULT NULL,
  reviewed_at datetime DEFAULT NULL,
  created_at timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at timestamp NULL DEFAULT NULL ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_forge_match_result_session_source (session_id, source_record_id),
  KEY idx_forge_match_result_session_status (session_id, status),
  KEY idx_forge_match_result_best_column (best_match_workspace_column_id),
  KEY idx_forge_match_result_manual_column (manually_selected_workspace_column_id),
  CONSTRAINT fk_forge_match_result_session
    FOREIGN KEY (session_id) REFERENCES forge_match_session (id)
    ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT fk_forge_match_result_source
    FOREIGN KEY (source_record_id) REFERENCES forge_match_source_record (id)
    ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT fk_forge_match_result_best_column
    FOREIGN KEY (best_match_workspace_column_id) REFERENCES workspace_column (id)
    ON DELETE SET NULL ON UPDATE CASCADE,
  CONSTRAINT fk_forge_match_result_manual_column
    FOREIGN KEY (manually_selected_workspace_column_id) REFERENCES workspace_column (id)
    ON DELETE SET NULL ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
