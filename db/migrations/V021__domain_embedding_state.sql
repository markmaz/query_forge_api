-- V021__domain_embedding_state.sql
-- Tracks domain embedding versions/hashes for incremental Qdrant indexing.

CREATE TABLE IF NOT EXISTS `domain_embedding_state` (
  `domain_id` BIGINT UNSIGNED NOT NULL,
  `workspace_id` VARCHAR(64) NULL,
  `vertical_norm` VARCHAR(50) NOT NULL DEFAULT 'generic',
  `domain_version` INT NOT NULL,
  `embedding_hash` CHAR(64) NOT NULL,
  `indexed_at` DATETIME NOT NULL,
  PRIMARY KEY (`domain_id`),
  KEY `idx_domain_embedding_state_vertical` (`vertical_norm`),
  KEY `idx_domain_embedding_state_ws` (`workspace_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
