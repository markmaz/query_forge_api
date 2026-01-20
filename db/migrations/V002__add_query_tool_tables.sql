-- V002__add_query_tool_tables.sql
-- Idempotent: safe to run multiple times.
-- Strategy:
--  - CREATE TABLE IF NOT EXISTS for new tables
--  - For indexes/constraints on existing tables: check information_schema first
--  - Avoid failing when objects already exist

-- ----------------------------
-- 1) workspace
-- ----------------------------
CREATE TABLE IF NOT EXISTS `workspace` (
  `id` varchar(128) NOT NULL,
  `display_name` varchar(255) DEFAULT NULL,
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- ----------------------------
-- 2) model_table
-- ----------------------------
CREATE TABLE IF NOT EXISTS `model_table` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT,
  `name` varchar(255) NOT NULL,
  `source_table_name` varchar(255) DEFAULT NULL,
  `description` text,
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` timestamp NULL DEFAULT NULL ON UPDATE CURRENT_TIMESTAMP,
  `origin` varchar(16) NOT NULL DEFAULT 'DBX',
  `is_missing_in_source` tinyint(1) NOT NULL DEFAULT '0',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_model_table_name` (`name`),
  UNIQUE KEY `uq_model_table_source_table_name` (`source_table_name`),
  KEY `ix_model_table_source_table_name` (`source_table_name`),
  KEY `ix_model_tbl_missing` (`is_missing_in_source`),
  KEY `ix_model_tbl_origin` (`origin`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- ----------------------------
-- 3) model_column
-- ----------------------------
CREATE TABLE IF NOT EXISTS `model_column` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT,
  `model_table_id` bigint unsigned NOT NULL,
  `column_name` varchar(255) NOT NULL,
  `data_type` longtext,
  `description` longtext,
  `ordinal_position` int NOT NULL DEFAULT '0',
  `nullable` tinyint(1) NOT NULL DEFAULT '1',
  `is_active` tinyint(1) NOT NULL DEFAULT '1',
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` timestamp NULL DEFAULT NULL ON UPDATE CURRENT_TIMESTAMP,
  `sample_values_json` longtext,
  `sample_stats_json` longtext,
  `sample_ran_at` timestamp NULL DEFAULT NULL,
  `sample_error` varchar(500) DEFAULT NULL,
  `origin` varchar(16) NOT NULL DEFAULT 'DBX',
  `is_missing_in_source` tinyint(1) NOT NULL DEFAULT '0',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_model_col` (`model_table_id`,`column_name`),
  KEY `ix_model_col_name` (`column_name`),
  KEY `ix_model_col_missing` (`is_missing_in_source`),
  KEY `ix_model_col_origin` (`origin`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- Add FK if missing (model_column.model_table_id -> model_table.id)
SET @exists_fk := (
  SELECT COUNT(*)
  FROM information_schema.table_constraints tc
  WHERE tc.constraint_schema = DATABASE()
    AND tc.table_name = 'model_column'
    AND tc.constraint_type = 'FOREIGN KEY'
    AND tc.constraint_name = 'fk_model_col_table'
);

SET @sql := IF(@exists_fk = 0,
  'ALTER TABLE `model_column` ADD CONSTRAINT `fk_model_col_table` FOREIGN KEY (`model_table_id`) REFERENCES `model_table` (`id`) ON DELETE CASCADE ON UPDATE CASCADE',
  'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- ----------------------------
-- 4) workspace_table
-- ----------------------------
CREATE TABLE IF NOT EXISTS `workspace_table` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT,
  `workspace_id` varchar(128) NOT NULL,
  `model_table_id` bigint unsigned DEFAULT NULL,
  `catalog_name` varchar(255) NOT NULL,
  `schema_name` varchar(255) NOT NULL DEFAULT 'asset',
  `table_name` varchar(255) NOT NULL,
  `full_name` varchar(600) NOT NULL,
  `variant_code` varchar(255) DEFAULT NULL,
  `is_qe` tinyint(1) NOT NULL DEFAULT '0',
  `exists_in_dbx` tinyint(1) NOT NULL DEFAULT '1',
  `last_seen_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` timestamp NULL DEFAULT NULL ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_ws_full` (`workspace_id`,`full_name`),
  KEY `ix_ws_model` (`workspace_id`,`model_table_id`),
  KEY `ix_ws_variant` (`workspace_id`,`variant_code`),
  KEY `ix_ws_unmapped` (`workspace_id`,`schema_name`,`model_table_id`,`table_name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- Add FK workspace_table.model_table_id -> model_table.id if missing
SET @exists_fk := (
  SELECT COUNT(*)
  FROM information_schema.table_constraints tc
  WHERE tc.constraint_schema = DATABASE()
    AND tc.table_name = 'workspace_table'
    AND tc.constraint_type = 'FOREIGN KEY'
    AND tc.constraint_name = 'fk_ws_table_model'
);
SET @sql := IF(@exists_fk = 0,
  'ALTER TABLE `workspace_table` ADD CONSTRAINT `fk_ws_table_model` FOREIGN KEY (`model_table_id`) REFERENCES `model_table` (`id`) ON DELETE RESTRICT ON UPDATE CASCADE',
  'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- Add FK workspace_table.workspace_id -> workspace.id if missing
SET @exists_fk := (
  SELECT COUNT(*)
  FROM information_schema.table_constraints tc
  WHERE tc.constraint_schema = DATABASE()
    AND tc.table_name = 'workspace_table'
    AND tc.constraint_type = 'FOREIGN KEY'
    AND tc.constraint_name = 'fk_ws_table_ws'
);
SET @sql := IF(@exists_fk = 0,
  'ALTER TABLE `workspace_table` ADD CONSTRAINT `fk_ws_table_ws` FOREIGN KEY (`workspace_id`) REFERENCES `workspace` (`id`) ON DELETE CASCADE ON UPDATE CASCADE',
  'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- ----------------------------
-- 5) workspace_column
-- ----------------------------
CREATE TABLE IF NOT EXISTS `workspace_column` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT,
  `workspace_table_id` bigint unsigned NOT NULL,
  `column_name` varchar(255) NOT NULL,
  `data_type` varchar(255) NOT NULL,
  `nullable` tinyint(1) NOT NULL DEFAULT '1',
  `ordinal_position` int NOT NULL DEFAULT '0',
  `exists_in_dbx` tinyint(1) NOT NULL DEFAULT '1',
  `last_seen_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` timestamp NULL DEFAULT NULL ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_wscol` (`workspace_table_id`,`column_name`),
  KEY `ix_wscol_name` (`column_name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- Add FK workspace_column.workspace_table_id -> workspace_table.id if missing
SET @exists_fk := (
  SELECT COUNT(*)
  FROM information_schema.table_constraints tc
  WHERE tc.constraint_schema = DATABASE()
    AND tc.table_name = 'workspace_column'
    AND tc.constraint_type = 'FOREIGN KEY'
    AND tc.constraint_name = 'fk_wscol_table'
);
SET @sql := IF(@exists_fk = 0,
  'ALTER TABLE `workspace_column` ADD CONSTRAINT `fk_wscol_table` FOREIGN KEY (`workspace_table_id`) REFERENCES `workspace_table` (`id`) ON DELETE CASCADE ON UPDATE CASCADE',
  'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- ----------------------------
-- 6) domain
-- ----------------------------
CREATE TABLE IF NOT EXISTS `domain` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT,
  `workspace_id` varchar(128) NOT NULL,
  `name` varchar(255) NOT NULL,
  `kind` text,
  `description` text,
  `is_active` tinyint(1) NOT NULL DEFAULT '1',
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` timestamp NULL DEFAULT NULL ON UPDATE CURRENT_TIMESTAMP,
  `model_table_id` bigint unsigned DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_domain_ws_name` (`workspace_id`,`name`),
  KEY `ix_domain_ws` (`workspace_id`),
  KEY `ix_domain_model_table_id` (`model_table_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- Add FK domain.model_table_id -> model_table.id if missing
SET @exists_fk := (
  SELECT COUNT(*)
  FROM information_schema.table_constraints tc
  WHERE tc.constraint_schema = DATABASE()
    AND tc.table_name = 'domain'
    AND tc.constraint_type = 'FOREIGN KEY'
    AND tc.constraint_name = 'fk_domain_model_table'
);
SET @sql := IF(@exists_fk = 0,
  'ALTER TABLE `domain` ADD CONSTRAINT `fk_domain_model_table` FOREIGN KEY (`model_table_id`) REFERENCES `model_table` (`id`) ON DELETE RESTRICT ON UPDATE CASCADE',
  'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- Add FK domain.workspace_id -> workspace.id if missing
SET @exists_fk := (
  SELECT COUNT(*)
  FROM information_schema.table_constraints tc
  WHERE tc.constraint_schema = DATABASE()
    AND tc.table_name = 'domain'
    AND tc.constraint_type = 'FOREIGN KEY'
    AND tc.constraint_name = 'fk_domain_ws'
);
SET @sql := IF(@exists_fk = 0,
  'ALTER TABLE `domain` ADD CONSTRAINT `fk_domain_ws` FOREIGN KEY (`workspace_id`) REFERENCES `workspace` (`id`) ON DELETE CASCADE ON UPDATE CASCADE',
  'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- ----------------------------
-- 7) domain_workspace_table
-- ----------------------------
CREATE TABLE IF NOT EXISTS `domain_workspace_table` (
  `domain_id` bigint unsigned NOT NULL,
  `workspace_table_id` bigint unsigned NOT NULL,
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`domain_id`,`workspace_table_id`),
  KEY `ix_dwt_wst` (`workspace_table_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- Add FK domain_workspace_table.domain_id -> domain.id if missing
SET @exists_fk := (
  SELECT COUNT(*)
  FROM information_schema.table_constraints tc
  WHERE tc.constraint_schema = DATABASE()
    AND tc.table_name = 'domain_workspace_table'
    AND tc.constraint_type = 'FOREIGN KEY'
    AND tc.constraint_name = 'fk_dwt_domain'
);
SET @sql := IF(@exists_fk = 0,
  'ALTER TABLE `domain_workspace_table` ADD CONSTRAINT `fk_dwt_domain` FOREIGN KEY (`domain_id`) REFERENCES `domain` (`id`) ON DELETE CASCADE ON UPDATE CASCADE',
  'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- Add FK domain_workspace_table.workspace_table_id -> workspace_table.id if missing
SET @exists_fk := (
  SELECT COUNT(*)
  FROM information_schema.table_constraints tc
  WHERE tc.constraint_schema = DATABASE()
    AND tc.table_name = 'domain_workspace_table'
    AND tc.constraint_type = 'FOREIGN KEY'
    AND tc.constraint_name = 'fk_dwt_wst'
);
SET @sql := IF(@exists_fk = 0,
  'ALTER TABLE `domain_workspace_table` ADD CONSTRAINT `fk_dwt_wst` FOREIGN KEY (`workspace_table_id`) REFERENCES `workspace_table` (`id`) ON DELETE CASCADE ON UPDATE CASCADE',
  'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- ----------------------------
-- 8) user_domain_mapping
-- (NOTE: user_id references users.user_id in your baseline; keep FK optional here.)
-- ----------------------------
CREATE TABLE IF NOT EXISTS `user_domain_mapping` (
  `user_id` varchar(255) NOT NULL,
  `domain_id` bigint unsigned NOT NULL,
  `can_read` tinyint(1) NOT NULL DEFAULT '1',
  `can_edit` tinyint(1) NOT NULL DEFAULT '0',
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`user_id`,`domain_id`),
  KEY `ix_udm_domain` (`domain_id`),
  KEY `ix_udm_user` (`user_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- FK to domain if missing
SET @exists_fk := (
  SELECT COUNT(*)
  FROM information_schema.table_constraints tc
  WHERE tc.constraint_schema = DATABASE()
    AND tc.table_name = 'user_domain_mapping'
    AND tc.constraint_type = 'FOREIGN KEY'
    AND tc.constraint_name = 'fk_udm_domain'
);
SET @sql := IF(@exists_fk = 0,
  'ALTER TABLE `user_domain_mapping` ADD CONSTRAINT `fk_udm_domain` FOREIGN KEY (`domain_id`) REFERENCES `domain` (`id`) ON DELETE CASCADE ON UPDATE CASCADE',
  'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- ----------------------------
-- 9) Saved Queries (new system)
-- ----------------------------
CREATE TABLE IF NOT EXISTS `saved_query_folder` (
  `id` char(36) NOT NULL DEFAULT (uuid()),
  `scope` varchar(16) NOT NULL,
  `workspace_id` varchar(128) DEFAULT NULL,
  `owner_user_id` char(36) DEFAULT NULL,
  `parent_id` char(36) DEFAULT NULL,
  `name` varchar(255) NOT NULL,
  `sort_index` int NOT NULL DEFAULT '0',
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  `is_deleted` tinyint(1) NOT NULL DEFAULT '0',
  `deleted_at` timestamp NULL DEFAULT NULL,
  `deleted_by_user_id` char(36) DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_sqf_sibling_name` (`scope`,`workspace_id`,`owner_user_id`,`parent_id`,`name`),
  KEY `idx_sqf_lookup` (`workspace_id`,`scope`,`owner_user_id`),
  KEY `idx_sqf_parent` (`parent_id`),
  KEY `idx_sqf_active_lookup` (`workspace_id`,`scope`,`owner_user_id`,`is_deleted`,`updated_at`),
  KEY `idx_sqf_trash_lookup` (`workspace_id`,`scope`,`owner_user_id`,`is_deleted`,`deleted_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- parent FK if missing
SET @exists_fk := (
  SELECT COUNT(*)
  FROM information_schema.table_constraints tc
  WHERE tc.constraint_schema = DATABASE()
    AND tc.table_name = 'saved_query_folder'
    AND tc.constraint_type = 'FOREIGN KEY'
    AND tc.constraint_name = 'fk_sqf_parent'
);
SET @sql := IF(@exists_fk = 0,
  'ALTER TABLE `saved_query_folder` ADD CONSTRAINT `fk_sqf_parent` FOREIGN KEY (`parent_id`) REFERENCES `saved_query_folder` (`id`) ON DELETE RESTRICT',
  'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

CREATE TABLE IF NOT EXISTS `saved_query` (
  `id` char(36) NOT NULL DEFAULT (uuid()),
  `scope` varchar(16) NOT NULL,
  `workspace_id` varchar(128) DEFAULT NULL,
  `owner_user_id` char(36) DEFAULT NULL,
  `folder_id` char(36) DEFAULT NULL,
  `title` varchar(255) NOT NULL,
  `description` text,
  `sql_json` longtext NOT NULL,
  `updated_by` char(36) DEFAULT NULL,
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  `is_deleted` tinyint(1) NOT NULL DEFAULT '0',
  `deleted_at` timestamp NULL DEFAULT NULL,
  `deleted_by_user_id` char(36) DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_sq_title_in_folder` (`scope`,`workspace_id`,`owner_user_id`,`folder_id`,`title`),
  KEY `idx_sq_lookup_mine` (`workspace_id`,`owner_user_id`,`scope`,`updated_at`),
  KEY `idx_sq_lookup_scope` (`scope`,`updated_at`),
  KEY `idx_sq_folder` (`folder_id`,`updated_at`),
  KEY `idx_sq_active_lookup` (`workspace_id`,`scope`,`owner_user_id`,`is_deleted`,`updated_at`),
  KEY `idx_sq_trash_lookup` (`workspace_id`,`scope`,`owner_user_id`,`is_deleted`,`deleted_at`),
  KEY `idx_sq_deleted_at` (`is_deleted`,`deleted_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- folder FK if missing
SET @exists_fk := (
  SELECT COUNT(*)
  FROM information_schema.table_constraints tc
  WHERE tc.constraint_schema = DATABASE()
    AND tc.table_name = 'saved_query'
    AND tc.constraint_type = 'FOREIGN KEY'
    AND tc.constraint_name = 'fk_sq_folder'
);
SET @sql := IF(@exists_fk = 0,
  'ALTER TABLE `saved_query` ADD CONSTRAINT `fk_sq_folder` FOREIGN KEY (`folder_id`) REFERENCES `saved_query_folder` (`id`) ON DELETE SET NULL',
  'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

CREATE TABLE IF NOT EXISTS `saved_query_acl` (
  `id` char(36) NOT NULL DEFAULT (uuid()),
  `saved_query_id` char(36) NOT NULL,
  `workspace_id` varchar(128) NOT NULL,
  `principal_type` varchar(16) NOT NULL,
  `principal_id` varchar(128) NOT NULL,
  `permission` varchar(16) NOT NULL,
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_sqa_unique` (`saved_query_id`,`principal_type`,`principal_id`),
  KEY `idx_sqa_principal` (`workspace_id`,`principal_type`,`principal_id`,`permission`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- FK to saved_query if missing
SET @exists_fk := (
  SELECT COUNT(*)
  FROM information_schema.table_constraints tc
  WHERE tc.constraint_schema = DATABASE()
    AND tc.table_name = 'saved_query_acl'
    AND tc.constraint_type = 'FOREIGN KEY'
    AND tc.constraint_name = 'fk_sqa_query'
);
SET @sql := IF(@exists_fk = 0,
  'ALTER TABLE `saved_query_acl` ADD CONSTRAINT `fk_sqa_query` FOREIGN KEY (`saved_query_id`) REFERENCES `saved_query` (`id`) ON DELETE CASCADE',
  'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;