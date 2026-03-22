-- Migration: 20260317_add_rbac.sql
--
-- Replaces existing product_roles / user_roles / user_global_roles /
-- user_role_map / roles with a clean RBAC system.
--
-- Existing role assignments are dropped on deploy.
-- Reassign roles via the admin UI after deploy.
--
-- Adaptations from staging:
--   user_roles.user_id       VARCHAR(255) — matches users.user_id (VARCHAR PK)
--   user_roles.granted_by    VARCHAR(255) — user identity, no FK
--   workspace_features.workspace_id VARCHAR(128) — matches workspace.id (VARCHAR PK)
--   workspace_features.granted_by   VARCHAR(255)
--   FK references:  users(user_id), workspace(id)  [singular table name]

-- ---------------------------------------------------------------------------
-- Drop old role tables (FK dependency order)
-- ---------------------------------------------------------------------------

SET FOREIGN_KEY_CHECKS = 0;

DROP TABLE IF EXISTS user_role_map;
DROP TABLE IF EXISTS user_roles;
DROP TABLE IF EXISTS user_global_roles;
DROP TABLE IF EXISTS product_roles;
DROP TABLE IF EXISTS roles;

SET FOREIGN_KEY_CHECKS = 1;

-- ---------------------------------------------------------------------------
-- roles — canonical role definitions
-- ---------------------------------------------------------------------------

CREATE TABLE roles (
    id              INT NOT NULL AUTO_INCREMENT,
    name            VARCHAR(64) NOT NULL,
    display_name    VARCHAR(128) NOT NULL,
    description     VARCHAR(500),
    feature_key     VARCHAR(64) NULL
        COMMENT 'NULL for global roles (super_admin, workspace_admin)',
    is_system       TINYINT(1) NOT NULL DEFAULT 1
        COMMENT 'System roles cannot be deleted via API',
    created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_roles_name (name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- ---------------------------------------------------------------------------
-- user_roles — user ↔ role assignments
-- ---------------------------------------------------------------------------

CREATE TABLE user_roles (
    id              INT NOT NULL AUTO_INCREMENT,
    user_id         VARCHAR(255) NOT NULL,
    workspace_id    VARCHAR(128) NULL
        COMMENT 'NULL only for global roles such as super_admin',
    role_id         INT NOT NULL,
    granted_by      VARCHAR(255) NULL
        COMMENT 'user_id of admin who assigned this role',
    granted_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_user_role_workspace (user_id, workspace_id, role_id),
    CONSTRAINT fk_user_roles_user
        FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    CONSTRAINT fk_user_roles_workspace
        FOREIGN KEY (workspace_id) REFERENCES workspace(id) ON DELETE CASCADE,
    CONSTRAINT fk_user_roles_role
        FOREIGN KEY (role_id) REFERENCES roles(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE INDEX ix_user_roles_user_id ON user_roles (user_id);
CREATE INDEX ix_user_roles_user_workspace ON user_roles (user_id, workspace_id);
CREATE INDEX ix_user_roles_role_id ON user_roles (role_id);

-- ---------------------------------------------------------------------------
-- workspace_features — workspace-level feature entitlements
-- ---------------------------------------------------------------------------

CREATE TABLE workspace_features (
    id              INT NOT NULL AUTO_INCREMENT,
    workspace_id    VARCHAR(128) NOT NULL,
    feature_key     VARCHAR(64) NOT NULL,
    is_active       TINYINT(1) NOT NULL DEFAULT 1,
    granted_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    granted_by      VARCHAR(255) NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_workspace_feature (workspace_id, feature_key),
    CONSTRAINT fk_workspace_features_workspace
        FOREIGN KEY (workspace_id) REFERENCES workspace(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE INDEX ix_workspace_features_workspace ON workspace_features (workspace_id, is_active);
