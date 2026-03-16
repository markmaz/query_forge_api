-- Migration: 20260316_add_workspace_destinations.sql
--
-- Adds the workspace_destinations table for the Destinations feature.
-- Destinations are workspace-level notification targets (Slack, Teams,
-- webhooks, email groups) referenced by destination_id in skill configs.
--
-- Run against the application database before deploying v6.

CREATE TABLE workspace_destinations (
    id                      INT NOT NULL AUTO_INCREMENT,
    workspace_id            VARCHAR(128) NOT NULL,
    name                    VARCHAR(255) NOT NULL,
    description             VARCHAR(500) NULL,
    destination_type        ENUM('slack', 'teams', 'webhook', 'email_group') NOT NULL,

    -- Fernet-encrypted JSON blob: all type-specific config incl. webhook URLs
    config_json_encrypted   TEXT NOT NULL,

    is_active               TINYINT(1) NOT NULL DEFAULT 1,

    -- Test tracking
    last_tested_at          DATETIME NULL,
    last_test_status        ENUM('success', 'failed') NULL,
    last_test_message       TEXT NULL,

    -- Usage tracking
    last_used_at            DATETIME NULL,
    usage_count             INT NOT NULL DEFAULT 0,

    -- Audit
    created_by              INT NULL,
    updated_by              INT NULL,
    created_at              DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at              DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE INDEX ix_workspace_destinations_workspace
    ON workspace_destinations (workspace_id, is_active);

CREATE INDEX ix_workspace_destinations_type
    ON workspace_destinations (workspace_id, destination_type);
