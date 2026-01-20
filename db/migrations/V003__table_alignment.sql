DROP TABLE IF EXISTS `domain_model_table`;
DROP TABLE IF EXISTS `saved_queries`;
DROP TABLE IF EXISTS `saved_query_recent`;
DROP TABLE IF EXISTS `organizations`;

-- V003__multi_table_domain_graph.sql
-- Adds multi-table domain support using a graph model:
--   - domain_workspace_table = nodes
--   - domain_table_join      = edges
-- Idempotent.

-- ============================================================
-- 1) domain_workspace_table: add node metadata (if missing)
-- ============================================================

SET @tbl := 'domain_workspace_table';

-- role
SET @col := 'role';
SET @exists := (
  SELECT COUNT(*) FROM information_schema.columns
  WHERE table_schema = DATABASE() AND table_name = @tbl AND column_name = @col
);
SET @sql := IF(@exists=0,
  'ALTER TABLE `domain_workspace_table` ADD COLUMN `role` varchar(64) DEFAULT NULL',
  'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- is_primary
SET @col := 'is_primary';
SET @exists := (
  SELECT COUNT(*) FROM information_schema.columns
  WHERE table_schema = DATABASE() AND table_name = @tbl AND column_name = @col
);
SET @sql := IF(@exists=0,
  'ALTER TABLE `domain_workspace_table` ADD COLUMN `is_primary` tinyint(1) NOT NULL DEFAULT 0',
  'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- relation_kind
SET @col := 'relation_kind';
SET @exists := (
  SELECT COUNT(*) FROM information_schema.columns
  WHERE table_schema = DATABASE() AND table_name = @tbl AND column_name = @col
);
SET @sql := IF(@exists=0,
  'ALTER TABLE `domain_workspace_table` ADD COLUMN `relation_kind` enum(''JOIN'',''UNION'') NOT NULL DEFAULT ''JOIN''',
  'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- sort_order
SET @col := 'sort_order';
SET @exists := (
  SELECT COUNT(*) FROM information_schema.columns
  WHERE table_schema = DATABASE() AND table_name = @tbl AND column_name = @col
);
SET @sql := IF(@exists=0,
  'ALTER TABLE `domain_workspace_table` ADD COLUMN `sort_order` int NOT NULL DEFAULT 0',
  'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- optional: alias (very useful later; harmless now)
SET @col := 'table_alias';
SET @exists := (
  SELECT COUNT(*) FROM information_schema.columns
  WHERE table_schema = DATABASE() AND table_name = @tbl AND column_name = @col
);
SET @sql := IF(@exists=0,
  'ALTER TABLE `domain_workspace_table` ADD COLUMN `table_alias` varchar(64) DEFAULT NULL',
  'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- Enforce only one primary per domain via generated column + unique index
SET @col := 'primary_key_once';
SET @exists := (
  SELECT COUNT(*) FROM information_schema.columns
  WHERE table_schema = DATABASE() AND table_name = @tbl AND column_name = @col
);
SET @sql := IF(@exists=0,
  'ALTER TABLE `domain_workspace_table`
     ADD COLUMN `primary_key_once` tinyint GENERATED ALWAYS AS (IF(`is_primary` = 1, 1, NULL)) STORED',
  'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @idx := 'uq_dwt_one_primary_per_domain';
SET @exists := (
  SELECT COUNT(*) FROM information_schema.statistics
  WHERE table_schema = DATABASE() AND table_name = @tbl AND index_name = @idx
);
SET @sql := IF(@exists=0,
  'CREATE UNIQUE INDEX `uq_dwt_one_primary_per_domain`
     ON `domain_workspace_table` (`domain_id`, `primary_key_once`)',
  'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- Helpful index for ordering nodes
SET @idx := 'ix_dwt_domain_sort';
SET @exists := (
  SELECT COUNT(*) FROM information_schema.statistics
  WHERE table_schema = DATABASE() AND table_name = @tbl AND index_name = @idx
);
SET @sql := IF(@exists=0,
  'CREATE INDEX `ix_dwt_domain_sort` ON `domain_workspace_table` (`domain_id`,`sort_order`)',
  'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- ============================================================
-- 2) domain_table_join: edge table
-- ============================================================

CREATE TABLE IF NOT EXISTS `domain_table_join` (
  `id` char(36) NOT NULL DEFAULT (uuid()),
  `domain_id` bigint unsigned NOT NULL,

  -- edge direction: "from" table is already in the current plan;
  -- "to" table is the one being added.
  `from_workspace_table_id` bigint unsigned NOT NULL,
  `to_workspace_table_id` bigint unsigned NOT NULL,

  `join_type` enum('INNER','LEFT','RIGHT') NOT NULL DEFAULT 'LEFT',

  -- machine-readable join definition
  -- recommended shape:
  -- { "on":[ {"left":{"table":"from","col":"patient_id"}, "right":{"table":"to","col":"patient_id"}} ],
  --   "extra":[ "to.year >= 2020" ] }
  `join_spec_json` json NOT NULL,

  `sort_order` int NOT NULL DEFAULT 0,
  `is_active` tinyint(1) NOT NULL DEFAULT 1,

  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` timestamp NULL DEFAULT NULL ON UPDATE CURRENT_TIMESTAMP,

  PRIMARY KEY (`id`),

  KEY `ix_dtj_domain` (`domain_id`),
  KEY `ix_dtj_from` (`domain_id`,`from_workspace_table_id`),
  KEY `ix_dtj_to` (`domain_id`,`to_workspace_table_id`),
  KEY `ix_dtj_domain_sort` (`domain_id`,`sort_order`),

  UNIQUE KEY `uq_dtj_edge` (`domain_id`,`from_workspace_table_id`,`to_workspace_table_id`,`sort_order`),

  CONSTRAINT `fk_dtj_domain`
    FOREIGN KEY (`domain_id`) REFERENCES `domain` (`id`)
    ON DELETE CASCADE ON UPDATE CASCADE,

  CONSTRAINT `fk_dtj_from_wst`
    FOREIGN KEY (`from_workspace_table_id`) REFERENCES `workspace_table` (`id`)
    ON DELETE RESTRICT ON UPDATE CASCADE,

  CONSTRAINT `fk_dtj_to_wst`
    FOREIGN KEY (`to_workspace_table_id`) REFERENCES `workspace_table` (`id`)
    ON DELETE RESTRICT ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;