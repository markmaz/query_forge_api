-- V018__user_level_rbac.sql
-- Adds direct user-level RBAC without changing existing product-role mappings.

CREATE TABLE IF NOT EXISTS `user_global_roles` (
  `user_global_role_id` INT NOT NULL AUTO_INCREMENT,
  `user_id` VARCHAR(45) NOT NULL,
  `role_id` VARCHAR(45) NOT NULL,
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`user_global_role_id`),
  UNIQUE KEY `uq_user_global_roles_user_role` (`user_id`, `role_id`),
  KEY `ix_user_global_roles_user_id` (`user_id`),
  KEY `ix_user_global_roles_role_id` (`role_id`),
  CONSTRAINT `fk_user_global_roles_user`
    FOREIGN KEY (`user_id`) REFERENCES `users` (`user_id`)
    ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT `fk_user_global_roles_role`
    FOREIGN KEY (`role_id`) REFERENCES `roles` (`role_id`)
    ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

