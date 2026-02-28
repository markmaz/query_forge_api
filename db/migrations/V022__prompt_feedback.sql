-- V022__prompt_feedback.sql
-- Stores thumbs up/down feedback for prompt responses.
-- If your MySQL variant does not support JSON columns, use LONGTEXT for
-- response_json/meta_json and continue storing serialized JSON strings.

CREATE TABLE IF NOT EXISTS `prompt_feedback` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `workspace_id` VARCHAR(64) NOT NULL,
  `user_id` VARCHAR(255) NOT NULL,
  `trace_id` VARCHAR(64) NULL,
  `vote` ENUM('up','down') NOT NULL,
  `normalized_prompt` TEXT NULL,
  `prompt_text` TEXT NULL,
  `response_json` JSON NOT NULL,
  `meta_json` JSON NULL,
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_pf_workspace_user_trace` (`workspace_id`, `user_id`, `trace_id`),
  KEY `idx_pf_workspace_user_created` (`workspace_id`, `user_id`, `created_at`),
  KEY `idx_pf_trace` (`trace_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
