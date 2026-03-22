-- Migration: 20260319_scope_user_roles_to_workspace.sql
--
-- Converts user_roles from global assignments to workspace-scoped assignments.
-- Only super_admin remains global (workspace_id NULL).
--
-- Existing non-super_admin rows are expanded across the user's current
-- workspace_membership rows so access is preserved per workspace.

SET FOREIGN_KEY_CHECKS = 0;

DROP TABLE IF EXISTS user_roles_new;

CREATE TABLE user_roles_new (
    id              INT NOT NULL AUTO_INCREMENT,
    user_id         VARCHAR(255) NOT NULL,
    workspace_id    VARCHAR(128) NULL
        COMMENT 'NULL only for global roles such as super_admin',
    role_id         INT NOT NULL,
    granted_by      VARCHAR(255) NULL,
    granted_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_user_role_workspace (user_id, workspace_id, role_id),
    KEY ix_user_roles_user_id (user_id),
    KEY ix_user_roles_user_workspace (user_id, workspace_id),
    KEY ix_user_roles_role_id (role_id),
    CONSTRAINT fk_user_roles_new_user
        FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    CONSTRAINT fk_user_roles_new_workspace
        FOREIGN KEY (workspace_id) REFERENCES workspace(id) ON DELETE CASCADE,
    CONSTRAINT fk_user_roles_new_role
        FOREIGN KEY (role_id) REFERENCES roles(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

INSERT INTO user_roles_new (user_id, workspace_id, role_id, granted_by, granted_at)
SELECT ur.user_id, NULL AS workspace_id, ur.role_id, ur.granted_by, ur.granted_at
FROM user_roles ur
JOIN roles r ON r.id = ur.role_id
WHERE r.name = 'super_admin';

INSERT IGNORE INTO user_roles_new (user_id, workspace_id, role_id, granted_by, granted_at)
SELECT ur.user_id, wm.workspace_id, ur.role_id, ur.granted_by, ur.granted_at
FROM user_roles ur
JOIN roles r ON r.id = ur.role_id
JOIN workspace_membership wm ON wm.user_id = ur.user_id
WHERE r.name <> 'super_admin';

-- Preserve non-super_admin rows for users with no workspace membership so they
-- can be reviewed manually after migration. Runtime RBAC ignores these NULL
-- workspace rows for non-global roles.
INSERT IGNORE INTO user_roles_new (user_id, workspace_id, role_id, granted_by, granted_at)
SELECT ur.user_id, NULL AS workspace_id, ur.role_id, ur.granted_by, ur.granted_at
FROM user_roles ur
JOIN roles r ON r.id = ur.role_id
LEFT JOIN workspace_membership wm ON wm.user_id = ur.user_id
WHERE r.name <> 'super_admin'
  AND wm.id IS NULL;

DROP TABLE user_roles;
RENAME TABLE user_roles_new TO user_roles;

SET FOREIGN_KEY_CHECKS = 1;
