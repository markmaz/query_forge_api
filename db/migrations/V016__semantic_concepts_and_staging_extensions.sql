-- V016__semantic_concepts_and_staging_extensions.sql

CREATE TABLE IF NOT EXISTS `semantic_concept` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `vertical_norm` VARCHAR(50) NOT NULL DEFAULT 'generic',
  `concept_key` VARCHAR(150) NOT NULL,
  `name` VARCHAR(200) NOT NULL,
  `description` TEXT NULL,
  `semantic_type` VARCHAR(50) NOT NULL,
  `sub_type` VARCHAR(200) NULL,
  `entity` VARCHAR(100) NULL,
  `granularity_rank` INT NOT NULL DEFAULT 0,
  `filter_allowed` TINYINT(1) NOT NULL DEFAULT 1,
  `group_by_allowed` TINYINT(1) NOT NULL DEFAULT 1,
  `aggregation_allowed` TINYINT(1) NOT NULL DEFAULT 0,
  `is_identifier` TINYINT(1) NOT NULL DEFAULT 0,
  `is_metric` TINYINT(1) NOT NULL DEFAULT 0,
  `display_priority` INT NOT NULL DEFAULT 0,
  `sensitive` TINYINT(1) NOT NULL DEFAULT 0,
  `status` VARCHAR(20) NOT NULL DEFAULT 'active',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_concept_vertical_key` (`vertical_norm`, `concept_key`),
  KEY `idx_concept_vertical_type` (`vertical_norm`, `semantic_type`),
  KEY `idx_concept_key` (`concept_key`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `semantic_concept_alias` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `vertical_norm` VARCHAR(50) NOT NULL DEFAULT 'generic',
  `alias_key` VARCHAR(200) NOT NULL,
  `concept_key` VARCHAR(150) NOT NULL,
  `match_kind` VARCHAR(20) NOT NULL DEFAULT 'exact',
  `weight` DECIMAL(4,3) NOT NULL DEFAULT 1.000,
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_alias` (`vertical_norm`, `alias_key`, `match_kind`),
  KEY `idx_alias_vertical` (`vertical_norm`),
  KEY `idx_alias_concept` (`vertical_norm`, `concept_key`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

ALTER TABLE `semantic_suggestion_item`
  ADD COLUMN `proposed_concept_id` BIGINT UNSIGNED NULL AFTER `proposed_concept_key`,
  ADD COLUMN `proposed_concept_source` VARCHAR(30) NOT NULL DEFAULT 'llm' AFTER `proposed_concept_id`,
  ADD COLUMN `proposed_fallback_concept` TINYINT(1) NOT NULL DEFAULT 0 AFTER `proposed_concept_source`,
  ADD COLUMN `proposed_concept_key_raw` VARCHAR(200) NULL AFTER `proposed_fallback_concept`;

ALTER TABLE `semantic_suggestion_item`
  ADD KEY `idx_item_concept` (`proposed_concept_id`),
  ADD KEY `idx_item_concept_source` (`proposed_concept_source`);
