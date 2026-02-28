-- U014__semantic_registry_graph.sql
-- Drops semantic graph tables and restores prior semantic_registry table.

DROP TABLE IF EXISTS `semantic_relationship`;
DROP TABLE IF EXISTS `semantic_column_map`;
DROP TABLE IF EXISTS `semantic_registry`;

CREATE TABLE IF NOT EXISTS `semantic_registry` (
  `id` CHAR(36) NOT NULL DEFAULT (UUID()),
  `vertical` VARCHAR(50) NULL,
  `concept_key` VARCHAR(150) NOT NULL,
  `semantic_type` VARCHAR(50) NOT NULL,
  `sub_type` VARCHAR(200) NULL,
  `entity` VARCHAR(100) NULL,
  `description` TEXT NULL,
  `granularity_rank` INT NOT NULL DEFAULT 0,
  `filter_allowed` TINYINT(1) NOT NULL DEFAULT 1,
  `group_by_allowed` TINYINT(1) NOT NULL DEFAULT 1,
  `aggregation_allowed` TINYINT(1) NOT NULL DEFAULT 1,
  `identifier` TINYINT(1) NOT NULL DEFAULT 0,
  `metric` TINYINT(1) NOT NULL DEFAULT 0,
  `display_priority` INT NOT NULL DEFAULT 0,
  `sensitive` TINYINT(1) NOT NULL DEFAULT 0,
  `created_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_semantic_registry_concept_key` (`concept_key`),
  KEY `ix_semantic_registry_vertical` (`vertical`),
  KEY `ix_semantic_registry_semantic_type` (`semantic_type`),
  KEY `ix_semantic_registry_sub_type` (`sub_type`),
  KEY `ix_semantic_registry_entity` (`entity`),
  KEY `ix_semantic_registry_vertical_type` (`vertical`, `semantic_type`),
  KEY `ix_semantic_registry_flags` (`filter_allowed`, `group_by_allowed`, `aggregation_allowed`, `identifier`, `metric`, `sensitive`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
