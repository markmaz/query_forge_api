-- Domain-level time policy configuration
-- Date: 2026-03-11
-- Notes:
--   - Dedicated table for deterministic planner time behavior.
--   - Scoped by workspace_id + domain_id.

CREATE TABLE IF NOT EXISTS `domain_time_policy` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT,
  `workspace_id` varchar(128) NOT NULL,
  `domain_id` bigint unsigned NOT NULL,
  `calendar_mode` varchar(16) NOT NULL DEFAULT 'calendar',
  `fiscal_year_start_month` tinyint unsigned DEFAULT NULL,
  `timezone` varchar(64) DEFAULT NULL,
  `week_start` varchar(16) NOT NULL DEFAULT 'monday',
  `default_time_concept_key` varchar(128) DEFAULT NULL,
  `allow_relative_ranges` tinyint(1) NOT NULL DEFAULT '1',
  `default_grain` varchar(16) DEFAULT NULL,
  `prefer_time_object_over_filter` tinyint(1) NOT NULL DEFAULT '1',
  `strict_mode` tinyint(1) NOT NULL DEFAULT '1',
  `relative_map` json DEFAULT NULL,
  `notes` text DEFAULT NULL,
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` timestamp NULL DEFAULT NULL ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_domain_time_policy` (`workspace_id`, `domain_id`),
  KEY `ix_domain_time_policy_domain` (`domain_id`),
  CONSTRAINT `fk_domain_time_policy_domain`
    FOREIGN KEY (`domain_id`) REFERENCES `domain` (`id`)
    ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COLLATE=utf8mb4_0900_ai_ci;

