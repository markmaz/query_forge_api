-- V023__forge_insights_threads_projects.sql
-- Persistent project/thread metadata for ForgeInsights chat UX.

CREATE TABLE IF NOT EXISTS `forge_insights_project` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `workspace_id` VARCHAR(64) NOT NULL,
  `user_id` VARCHAR(255) NOT NULL,
  `name` VARCHAR(255) NOT NULL,
  `description` TEXT NULL,
  `is_archived` TINYINT(1) NOT NULL DEFAULT 0,
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_fip_workspace_user_updated` (`workspace_id`, `user_id`, `updated_at`),
  KEY `idx_fip_workspace_user_archived` (`workspace_id`, `user_id`, `is_archived`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `forge_insights_thread` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `workspace_id` VARCHAR(64) NOT NULL,
  `user_id` VARCHAR(255) NOT NULL,
  `project_id` BIGINT UNSIGNED NULL,
  `conversation_id` VARCHAR(128) NOT NULL,
  `title` VARCHAR(255) NULL,
  `preview_text` TEXT NULL,
  `is_pinned` TINYINT(1) NOT NULL DEFAULT 0,
  `is_archived` TINYINT(1) NOT NULL DEFAULT 0,
  `last_message_at` DATETIME NULL,
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_fit_workspace_user_conversation` (`workspace_id`, `user_id`, `conversation_id`),
  KEY `idx_fit_workspace_user_last` (`workspace_id`, `user_id`, `last_message_at`),
  KEY `idx_fit_workspace_user_updated` (`workspace_id`, `user_id`, `updated_at`),
  KEY `idx_fit_project_updated` (`project_id`, `updated_at`),
  CONSTRAINT `fk_fit_project`
    FOREIGN KEY (`project_id`)
    REFERENCES `forge_insights_project` (`id`)
    ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
