-- V024__forge_insights_conversation_history.sql
-- Durable ForgeInsights conversation/message persistence (MySQL source of truth).

CREATE TABLE IF NOT EXISTS `forge_insights_conversation` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `workspace_id` VARCHAR(64) NOT NULL,
  `user_id` VARCHAR(255) NOT NULL,
  `conversation_id` VARCHAR(128) NOT NULL,
  `title` VARCHAR(255) NULL,
  `summary` LONGTEXT NULL,
  `message_count` INT UNSIGNED NOT NULL DEFAULT 0,
  `last_message_at` DATETIME NULL,
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_fic_workspace_user_conversation` (`workspace_id`, `user_id`, `conversation_id`),
  KEY `idx_fic_workspace_user_updated` (`workspace_id`, `user_id`, `updated_at`),
  KEY `idx_fic_workspace_user_last` (`workspace_id`, `user_id`, `last_message_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `forge_insights_message` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `conversation_pk` BIGINT UNSIGNED NOT NULL,
  `seq_no` INT UNSIGNED NOT NULL,
  `role` ENUM('user', 'assistant', 'system') NOT NULL,
  `content` LONGTEXT NOT NULL,
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_fim_conversation_seq` (`conversation_pk`, `seq_no`, `id`),
  CONSTRAINT `fk_fim_conversation`
    FOREIGN KEY (`conversation_pk`)
    REFERENCES `forge_insights_conversation` (`id`)
    ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
