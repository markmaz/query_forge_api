-- V014__semantic_registry_graph.sql
-- Creates vertical-agnostic semantic registry, column mapping, and relationship graph tables.

DROP TABLE IF EXISTS `semantic_relationship`;
DROP TABLE IF EXISTS `semantic_column_map`;
DROP TABLE IF EXISTS `semantic_registry`;

CREATE TABLE `semantic_registry` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `vertical` VARCHAR(50) NULL,
  `vertical_norm` VARCHAR(50) GENERATED ALWAYS AS (IFNULL(`vertical`, '__global__')) STORED,
  `concept_key` VARCHAR(150) NOT NULL,
  `semantic_type` VARCHAR(50) NOT NULL,
  `sub_type` VARCHAR(200) NULL,
  `entity` VARCHAR(100) NULL,
  `description` TEXT NULL,
  `granularity_rank` INT NOT NULL DEFAULT 0,
  `filter_allowed` TINYINT(1) NOT NULL DEFAULT 1,
  `group_by_allowed` TINYINT(1) NOT NULL DEFAULT 1,
  `aggregation_allowed` TINYINT(1) NOT NULL DEFAULT 1,
  `is_identifier` TINYINT(1) NOT NULL DEFAULT 0,
  `is_metric` TINYINT(1) NOT NULL DEFAULT 0,
  `display_priority` INT NOT NULL DEFAULT 0,
  `sensitive` TINYINT(1) NOT NULL DEFAULT 0,
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_semantic_registry_vertical_concept` (`vertical_norm`, `concept_key`),
  KEY `idx_semantic_registry_vertical_type` (`vertical_norm`, `semantic_type`),
  KEY `idx_semantic_registry_vertical_entity` (`vertical_norm`, `entity`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `semantic_column_map` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `semantic_registry_id` BIGINT UNSIGNED NOT NULL,
  `workspace_id` VARCHAR(100) NULL,
  `workspace_norm` VARCHAR(100) GENERATED ALWAYS AS (IFNULL(`workspace_id`, '__global__')) STORED,
  `model_column_id` BIGINT UNSIGNED NULL,
  `table_name` VARCHAR(200) NULL,
  `column_name` VARCHAR(200) NULL,
  `priority_rank` INT NOT NULL DEFAULT 0,
  `confidence_score` DECIMAL(4,3) NULL,
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_map_semreg_workspace_modelcol` (`semantic_registry_id`, `workspace_norm`, `model_column_id`),
  UNIQUE KEY `uq_map_semreg_workspace_tablecol` (`semantic_registry_id`, `workspace_norm`, `table_name`, `column_name`),
  KEY `idx_map_workspace_modelcol` (`workspace_norm`, `model_column_id`),
  KEY `idx_map_workspace_tablecol` (`workspace_norm`, `table_name`, `column_name`),
  CONSTRAINT `fk_semantic_map_registry`
    FOREIGN KEY (`semantic_registry_id`) REFERENCES `semantic_registry` (`id`) ON DELETE CASCADE,
  CONSTRAINT `chk_semantic_map_confidence`
    CHECK (`confidence_score` IS NULL OR (`confidence_score` >= 0.000 AND `confidence_score` <= 1.000))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `semantic_relationship` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `parent_concept_id` BIGINT UNSIGNED NOT NULL,
  `child_concept_id` BIGINT UNSIGNED NOT NULL,
  `relationship_type` VARCHAR(100) NOT NULL,
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_rel` (`parent_concept_id`, `child_concept_id`, `relationship_type`),
  KEY `idx_rel_parent` (`parent_concept_id`),
  KEY `idx_rel_child` (`child_concept_id`),
  CONSTRAINT `fk_semantic_rel_parent`
    FOREIGN KEY (`parent_concept_id`) REFERENCES `semantic_registry` (`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_semantic_rel_child`
    FOREIGN KEY (`child_concept_id`) REFERENCES `semantic_registry` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
