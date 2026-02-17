-- V013__create_semantic_registry.sql
-- Vertical-agnostic semantic registry for business meaning metadata.

CREATE TABLE IF NOT EXISTS `semantic_registry` (
  `id` CHAR(36) NOT NULL DEFAULT (UUID()) COMMENT 'Primary UUID for semantic_registry row',
  `vertical` VARCHAR(50) NULL COMMENT 'Optional vertical/domain scope (education, healthcare, finance); NULL means global',
  `concept_key` VARCHAR(150) NOT NULL COMMENT 'Globally unique concept key used by planners/rankers',
  `semantic_type` VARCHAR(50) NOT NULL COMMENT 'entity|identifier|attribute|geography|time|metric|flag|reference',
  `sub_type` VARCHAR(200) NULL COMMENT 'Optional fine-grained subtype (e.g. attribute.student.first_name)',
  `entity` VARCHAR(100) NULL COMMENT 'Business entity name associated to this concept',
  `description` TEXT NULL COMMENT 'Human-readable business description',
  `granularity_rank` INT NOT NULL DEFAULT 0 COMMENT 'Lower is more specific',
  `filter_allowed` TINYINT(1) NOT NULL DEFAULT 1 COMMENT 'Whether this concept can be used in filters',
  `group_by_allowed` TINYINT(1) NOT NULL DEFAULT 1 COMMENT 'Whether this concept can be grouped',
  `aggregation_allowed` TINYINT(1) NOT NULL DEFAULT 1 COMMENT 'Whether this concept can be aggregated',
  `identifier` TINYINT(1) NOT NULL DEFAULT 0 COMMENT 'True if concept is an identifier',
  `metric` TINYINT(1) NOT NULL DEFAULT 0 COMMENT 'True if concept is numeric/aggregatable',
  `display_priority` INT NOT NULL DEFAULT 0 COMMENT 'Higher/Lower UI display priority (consumer-defined)',
  `sensitive` TINYINT(1) NOT NULL DEFAULT 0 COMMENT 'True if concept may contain sensitive data',
  `created_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT 'Creation timestamp (UTC)',
  `updated_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT 'Last update timestamp (UTC)',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_semantic_registry_concept_key` (`concept_key`),
  KEY `ix_semantic_registry_vertical` (`vertical`),
  KEY `ix_semantic_registry_semantic_type` (`semantic_type`),
  KEY `ix_semantic_registry_sub_type` (`sub_type`),
  KEY `ix_semantic_registry_entity` (`entity`),
  KEY `ix_semantic_registry_vertical_type` (`vertical`, `semantic_type`),
  KEY `ix_semantic_registry_flags` (`filter_allowed`, `group_by_allowed`, `aggregation_allowed`, `identifier`, `metric`, `sensitive`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

