-- V020__planner_llm_cache.sql
-- Cache store for planner_llm v2 responses.

CREATE TABLE IF NOT EXISTS `planner_cache` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `cache_key` CHAR(64) NOT NULL,
  `workspace_id` VARCHAR(64) NOT NULL,
  `vertical` VARCHAR(32) NOT NULL DEFAULT 'generic',
  `normalized_prompt` TEXT NOT NULL,
  `constraints_json` LONGTEXT NOT NULL,
  `registry_version` VARCHAR(64) NOT NULL,
  `plan_json` LONGTEXT NOT NULL,
  `sql_json` LONGTEXT NOT NULL,
  `validation_json` LONGTEXT NOT NULL,
  `candidates_json` LONGTEXT NULL,
  `expires_at` DATETIME NOT NULL,
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `ux_planner_cache_key` (`cache_key`),
  KEY `idx_planner_cache_lookup` (`workspace_id`, `vertical`, `registry_version`, `expires_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
