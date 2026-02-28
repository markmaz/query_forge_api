-- V019__nlp_review_queue.sql
-- Active-learning queue for Tier2 NLP review and correction.

CREATE TABLE IF NOT EXISTS `nlp_review_item` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `workspace_id` VARCHAR(64) NOT NULL,
  `prompt` TEXT NOT NULL,
  `model_version` VARCHAR(50) NOT NULL,
  `prediction_json` LONGTEXT NOT NULL,
  `corrected_json` LONGTEXT NULL,
  `status` VARCHAR(20) NOT NULL DEFAULT 'pending',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_nlp_review_ws_status` (`workspace_id`, `status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
