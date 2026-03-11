-- Workspace LLM configuration
-- Date: 2026-03-11
-- Adds workspace_llm table for per-workspace LLM role assignment.
-- workspace_id is VARCHAR (matches existing workspace identity pattern).
-- Unique "one active LLM per role per workspace" constraint is enforced in
-- the service layer — MySQL does not support partial unique indexes without
-- expression columns.

CREATE TABLE IF NOT EXISTS `workspace_llm` (
  `id`                bigint unsigned NOT NULL AUTO_INCREMENT,
  `workspace_id`      varchar(255) NOT NULL,
  `name`              varchar(255) NOT NULL,
  `provider`          varchar(64) NOT NULL,
  `model_name`        varchar(255) NOT NULL,
  `role`              varchar(64) NOT NULL,
  `api_key_encrypted` text DEFAULT NULL,
  `endpoint_url`      varchar(500) DEFAULT NULL,
  `is_active`         tinyint(1) NOT NULL DEFAULT '1',
  `config_json`       text DEFAULT NULL,
  `created_at`        timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`        timestamp NULL DEFAULT NULL ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `ix_workspace_llm_workspace` (`workspace_id`),
  KEY `ix_workspace_llm_workspace_role` (`workspace_id`, `role`),
  KEY `ix_workspace_llm_active` (`workspace_id`, `is_active`)
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COLLATE=utf8mb4_0900_ai_ci;
