SET @db_name = DATABASE();

SET @exists = (
  SELECT COUNT(*) FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = @db_name AND TABLE_NAME = 'forge_match_session' AND COLUMN_NAME = 'analysis_job_id'
);
SET @sql = IF(@exists = 0, 'ALTER TABLE forge_match_session ADD COLUMN analysis_job_id char(36) DEFAULT NULL', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @exists = (
  SELECT COUNT(*) FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = @db_name AND TABLE_NAME = 'forge_match_session' AND COLUMN_NAME = 'current_phase'
);
SET @sql = IF(@exists = 0, 'ALTER TABLE forge_match_session ADD COLUMN current_phase varchar(64) DEFAULT NULL', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @exists = (
  SELECT COUNT(*) FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = @db_name AND TABLE_NAME = 'forge_match_session' AND COLUMN_NAME = 'current_source_row_id'
);
SET @sql = IF(@exists = 0, 'ALTER TABLE forge_match_session ADD COLUMN current_source_row_id varchar(128) DEFAULT NULL', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @exists = (
  SELECT COUNT(*) FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = @db_name AND TABLE_NAME = 'forge_match_session' AND COLUMN_NAME = 'analyzed_count'
);
SET @sql = IF(@exists = 0, 'ALTER TABLE forge_match_session ADD COLUMN analyzed_count int NOT NULL DEFAULT 0', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @exists = (
  SELECT COUNT(*) FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = @db_name AND TABLE_NAME = 'forge_match_session' AND COLUMN_NAME = 'skipped_count'
);
SET @sql = IF(@exists = 0, 'ALTER TABLE forge_match_session ADD COLUMN skipped_count int NOT NULL DEFAULT 0', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @exists = (
  SELECT COUNT(*) FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = @db_name AND TABLE_NAME = 'forge_match_session' AND COLUMN_NAME = 'failed_count'
);
SET @sql = IF(@exists = 0, 'ALTER TABLE forge_match_session ADD COLUMN failed_count int NOT NULL DEFAULT 0', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @exists = (
  SELECT COUNT(*) FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = @db_name AND TABLE_NAME = 'forge_match_session' AND COLUMN_NAME = 'cancel_requested'
);
SET @sql = IF(@exists = 0, 'ALTER TABLE forge_match_session ADD COLUMN cancel_requested tinyint(1) NOT NULL DEFAULT 0', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @exists = (
  SELECT COUNT(*) FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = @db_name AND TABLE_NAME = 'forge_match_session' AND COLUMN_NAME = 'analysis_error'
);
SET @sql = IF(@exists = 0, 'ALTER TABLE forge_match_session ADD COLUMN analysis_error text DEFAULT NULL', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @exists = (
  SELECT COUNT(*) FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = @db_name AND TABLE_NAME = 'forge_match_session' AND COLUMN_NAME = 'last_heartbeat_at'
);
SET @sql = IF(@exists = 0, 'ALTER TABLE forge_match_session ADD COLUMN last_heartbeat_at datetime DEFAULT NULL', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @idx_exists = (
  SELECT COUNT(*) FROM information_schema.STATISTICS
  WHERE TABLE_SCHEMA = @db_name AND TABLE_NAME = 'forge_match_session' AND INDEX_NAME = 'idx_forge_match_session_analysis_job'
);
SET @sql = IF(@idx_exists = 0, 'CREATE INDEX idx_forge_match_session_analysis_job ON forge_match_session (analysis_job_id)', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;
