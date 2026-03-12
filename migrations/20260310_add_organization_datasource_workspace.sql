-- QueryForge tenancy + datasource refactor (additive, migration-safe)
-- Date: 2026-03-10
-- Notes:
--   - Keeps workspace_id as the primary application routing key.
--   - Adds organization + datasource entities and workspace foreign keys.
--   - Uses information_schema checks so repeated runs are safe.

SET @db_name := DATABASE();

CREATE TABLE IF NOT EXISTS `organization` (
  `id`            varchar(128) NOT NULL,
  `name`          varchar(255) NOT NULL,
  `slug`          varchar(255) NOT NULL,
  `description`   text DEFAULT NULL,
  `is_active`     tinyint(1) NOT NULL DEFAULT '1',
  `created_at`    timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`    timestamp NULL DEFAULT NULL ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_organization_slug` (`slug`),
  KEY `ix_organization_name` (`name`),
  KEY `ix_organization_active` (`is_active`)
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `organization_membership` (
  `id`               bigint unsigned NOT NULL AUTO_INCREMENT,
  `organization_id`  varchar(128) NOT NULL,
  `user_id`          varchar(255) NOT NULL,
  `role`             varchar(64) NOT NULL DEFAULT 'member',
  `is_active`        tinyint(1) NOT NULL DEFAULT '1',
  `created_at`       timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`       timestamp NULL DEFAULT NULL ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_org_membership` (`organization_id`, `user_id`),
  KEY `ix_org_membership_user` (`user_id`),
  KEY `ix_org_membership_org_role` (`organization_id`, `role`),
  KEY `ix_org_membership_active` (`organization_id`, `is_active`)
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `datasource` (
  `id`                bigint unsigned NOT NULL AUTO_INCREMENT,
  `organization_id`   varchar(128) NOT NULL,
  `name`              varchar(255) NOT NULL,
  `slug`              varchar(255) NOT NULL,
  `type`              varchar(32) NOT NULL,
  `description`       text DEFAULT NULL,
  `is_active`         tinyint(1) NOT NULL DEFAULT '1',
  `secret_ref`        varchar(512) DEFAULT NULL,
  `config_json`       json DEFAULT NULL,
  `last_tested_at`    datetime DEFAULT NULL,
  `last_test_status`  varchar(32) DEFAULT NULL,
  `last_test_message` varchar(1000) DEFAULT NULL,
  `created_at`        timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`        timestamp NULL DEFAULT NULL ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_datasource_org_slug` (`organization_id`, `slug`),
  UNIQUE KEY `uq_datasource_org_name` (`organization_id`, `name`),
  KEY `ix_datasource_org` (`organization_id`),
  KEY `ix_datasource_type` (`type`),
  KEY `ix_datasource_active` (`organization_id`, `is_active`),
  KEY `ix_datasource_test_status` (`last_test_status`)
  ,CONSTRAINT `chk_datasource_type`
    CHECK (`type` IN ('databricks', 'snowflake', 'mysql', 'postgres', 'bigquery'))
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `workspace_membership` (
  `id`             bigint unsigned NOT NULL AUTO_INCREMENT,
  `workspace_id`   varchar(128) NOT NULL,
  `user_id`        varchar(255) NOT NULL,
  `role`           varchar(64) NOT NULL DEFAULT 'member',
  `is_active`      tinyint(1) NOT NULL DEFAULT '1',
  `created_at`     timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`     timestamp NULL DEFAULT NULL ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_workspace_membership` (`workspace_id`, `user_id`),
  KEY `ix_workspace_membership_user` (`user_id`),
  KEY `ix_workspace_membership_workspace_role` (`workspace_id`, `role`)
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COLLATE=utf8mb4_0900_ai_ci;

DELIMITER $$

DROP PROCEDURE IF EXISTS qf_add_column_if_missing $$
CREATE PROCEDURE qf_add_column_if_missing(
  IN p_table_name VARCHAR(128),
  IN p_column_name VARCHAR(128),
  IN p_column_def TEXT
)
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = DATABASE()
      AND table_name = p_table_name
      AND column_name = p_column_name
  ) THEN
    SET @sql := CONCAT('ALTER TABLE `', p_table_name, '` ADD COLUMN ', p_column_def);
    PREPARE stmt FROM @sql;
    EXECUTE stmt;
    DEALLOCATE PREPARE stmt;
  END IF;
END $$

DROP PROCEDURE IF EXISTS qf_add_index_if_missing $$
CREATE PROCEDURE qf_add_index_if_missing(
  IN p_table_name VARCHAR(128),
  IN p_index_name VARCHAR(128),
  IN p_index_sql TEXT
)
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM information_schema.statistics
    WHERE table_schema = DATABASE()
      AND table_name = p_table_name
      AND index_name = p_index_name
  ) THEN
    SET @sql := p_index_sql;
    PREPARE stmt FROM @sql;
    EXECUTE stmt;
    DEALLOCATE PREPARE stmt;
  END IF;
END $$

DROP PROCEDURE IF EXISTS qf_add_fk_if_missing $$
CREATE PROCEDURE qf_add_fk_if_missing(
  IN p_table_name VARCHAR(128),
  IN p_constraint_name VARCHAR(128),
  IN p_fk_sql TEXT
)
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM information_schema.table_constraints
    WHERE table_schema = DATABASE()
      AND table_name = p_table_name
      AND constraint_name = p_constraint_name
      AND constraint_type = 'FOREIGN KEY'
  ) THEN
    SET @sql := p_fk_sql;
    PREPARE stmt FROM @sql;
    EXECUTE stmt;
    DEALLOCATE PREPARE stmt;
  END IF;
END $$

DROP PROCEDURE IF EXISTS qf_add_check_if_missing $$
CREATE PROCEDURE qf_add_check_if_missing(
  IN p_table_name VARCHAR(128),
  IN p_constraint_name VARCHAR(128),
  IN p_check_sql TEXT
)
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM information_schema.table_constraints
    WHERE table_schema = DATABASE()
      AND table_name = p_table_name
      AND constraint_name = p_constraint_name
      AND constraint_type = 'CHECK'
  ) THEN
    SET @sql := p_check_sql;
    PREPARE stmt FROM @sql;
    EXECUTE stmt;
    DEALLOCATE PREPARE stmt;
  END IF;
END $$

DELIMITER ;

CALL qf_add_column_if_missing('workspace', 'organization_id', '`organization_id` varchar(128) DEFAULT NULL');
CALL qf_add_column_if_missing('workspace', 'datasource_id', '`datasource_id` bigint unsigned DEFAULT NULL');
CALL qf_add_column_if_missing('workspace', 'name', '`name` varchar(255) DEFAULT NULL');
CALL qf_add_column_if_missing('workspace', 'description', '`description` text DEFAULT NULL');
CALL qf_add_column_if_missing('workspace', 'is_active', '`is_active` tinyint(1) NOT NULL DEFAULT 1');
CALL qf_add_column_if_missing('workspace', 'default_catalog', '`default_catalog` varchar(255) DEFAULT NULL');
CALL qf_add_column_if_missing('workspace', 'default_schema', '`default_schema` varchar(255) DEFAULT NULL');
CALL qf_add_column_if_missing('workspace', 'updated_at', '`updated_at` timestamp NULL DEFAULT NULL ON UPDATE CURRENT_TIMESTAMP');

CALL qf_add_index_if_missing('workspace', 'ix_workspace_org',
  'ALTER TABLE `workspace` ADD KEY `ix_workspace_org` (`organization_id`)');
CALL qf_add_index_if_missing('workspace', 'ix_workspace_datasource',
  'ALTER TABLE `workspace` ADD KEY `ix_workspace_datasource` (`datasource_id`)');
CALL qf_add_index_if_missing('workspace', 'ix_workspace_org_active',
  'ALTER TABLE `workspace` ADD KEY `ix_workspace_org_active` (`organization_id`, `is_active`)');

CALL qf_add_fk_if_missing(
  'organization_membership',
  'fk_org_membership_org',
  'ALTER TABLE `organization_membership` ADD CONSTRAINT `fk_org_membership_org` FOREIGN KEY (`organization_id`) REFERENCES `organization` (`id`) ON DELETE CASCADE ON UPDATE CASCADE'
);

CALL qf_add_fk_if_missing(
  'organization_membership',
  'fk_org_membership_user',
  'ALTER TABLE `organization_membership` ADD CONSTRAINT `fk_org_membership_user` FOREIGN KEY (`user_id`) REFERENCES `users` (`user_id`) ON DELETE CASCADE ON UPDATE CASCADE'
);

CALL qf_add_fk_if_missing(
  'datasource',
  'fk_datasource_org',
  'ALTER TABLE `datasource` ADD CONSTRAINT `fk_datasource_org` FOREIGN KEY (`organization_id`) REFERENCES `organization` (`id`) ON DELETE CASCADE ON UPDATE CASCADE'
);

CALL qf_add_check_if_missing(
  'datasource',
  'chk_datasource_type',
  'ALTER TABLE `datasource` ADD CONSTRAINT `chk_datasource_type` CHECK (`type` IN (''databricks'', ''snowflake'', ''mysql'', ''postgres'', ''bigquery''))'
);

CALL qf_add_fk_if_missing(
  'workspace',
  'fk_workspace_org',
  'ALTER TABLE `workspace` ADD CONSTRAINT `fk_workspace_org` FOREIGN KEY (`organization_id`) REFERENCES `organization` (`id`) ON DELETE CASCADE ON UPDATE CASCADE'
);

CALL qf_add_fk_if_missing(
  'workspace',
  'fk_workspace_datasource',
  'ALTER TABLE `workspace` ADD CONSTRAINT `fk_workspace_datasource` FOREIGN KEY (`datasource_id`) REFERENCES `datasource` (`id`) ON DELETE RESTRICT ON UPDATE CASCADE'
);

CALL qf_add_fk_if_missing(
  'workspace_membership',
  'fk_workspace_membership_workspace',
  'ALTER TABLE `workspace_membership` ADD CONSTRAINT `fk_workspace_membership_workspace` FOREIGN KEY (`workspace_id`) REFERENCES `workspace` (`id`) ON DELETE CASCADE ON UPDATE CASCADE'
);

CALL qf_add_fk_if_missing(
  'workspace_membership',
  'fk_workspace_membership_user',
  'ALTER TABLE `workspace_membership` ADD CONSTRAINT `fk_workspace_membership_user` FOREIGN KEY (`user_id`) REFERENCES `users` (`user_id`) ON DELETE CASCADE ON UPDATE CASCADE'
);

DROP PROCEDURE IF EXISTS qf_add_column_if_missing;
DROP PROCEDURE IF EXISTS qf_add_index_if_missing;
DROP PROCEDURE IF EXISTS qf_add_fk_if_missing;
DROP PROCEDURE IF EXISTS qf_add_check_if_missing;
