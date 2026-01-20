-- V001__baseline_prod.sql
-- Baseline schema (prod snapshot), ordered by FK dependencies.
-- NOTE: For MySQL, do NOT wrap DDL in BEGIN/COMMIT (DDL auto-commits).

CREATE TABLE `users` (
  `user_id` varchar(255) NOT NULL,
  `username` varchar(255) NOT NULL,
  `password` varchar(255) NOT NULL,
  `email` varchar(255) NOT NULL,
  `first_name` varchar(20) DEFAULT NULL,
  `last_name` varchar(30) DEFAULT NULL,
  `tos_accepted` tinyint(1) NOT NULL DEFAULT '0',
  `eula_accepted` tinyint(1) NOT NULL DEFAULT '0',
  `status` varchar(20) DEFAULT NULL,
  `otp_secret` varchar(100) DEFAULT NULL,
  `last_log_in` datetime DEFAULT NULL,
  `two_factor_preference` varchar(45) NOT NULL DEFAULT 'Email',
  PRIMARY KEY (`user_id`),
  UNIQUE KEY `email_UNIQUE` (`email`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE `roles` (
  `role_id` varchar(45) NOT NULL,
  `role_name` varchar(45) DEFAULT NULL,
  PRIMARY KEY (`role_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE `product_groups` (
  `product_group_id` varchar(45) NOT NULL,
  `product_group_name` varchar(100) NOT NULL,
  `status` varchar(45) NOT NULL DEFAULT 'Active',
  `last_update` datetime DEFAULT NULL,
  PRIMARY KEY (`product_group_id`),
  UNIQUE KEY `product_group_id_UNIQUE` (`product_group_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE `products` (
  `product_id` varchar(45) NOT NULL,
  `product_name` varchar(45) NOT NULL,
  `status` varchar(45) NOT NULL DEFAULT 'Active',
  `last_update` datetime DEFAULT NULL,
  `product_group_id` varchar(45) DEFAULT NULL,
  PRIMARY KEY (`product_id`),
  UNIQUE KEY `product_id_UNIQUE` (`product_id`),
  KEY `ix_products_product_group_id` (`product_group_id`),
  CONSTRAINT `fk_products_product_group`
    FOREIGN KEY (`product_group_id`) REFERENCES `product_groups` (`product_group_id`)
    ON DELETE SET NULL ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE `product_group_map` (
  `product_group_map_id` varchar(40) NOT NULL,
  `product_id` varchar(45) NOT NULL,
  `product_group_id` varchar(45) NOT NULL,
  PRIMARY KEY (`product_group_map_id`),
  KEY `ix_pgm_product_id` (`product_id`),
  KEY `ix_pgm_product_group_id` (`product_group_id`),
  CONSTRAINT `fk_pgm_product`
    FOREIGN KEY (`product_id`) REFERENCES `products` (`product_id`)
    ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT `fk_pgm_product_group`
    FOREIGN KEY (`product_group_id`) REFERENCES `product_groups` (`product_group_id`)
    ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE `product_roles` (
  `product_role_id` varchar(45) NOT NULL,
  `product_id` varchar(45) NOT NULL,
  `role_id` varchar(45) NOT NULL,
  PRIMARY KEY (`product_role_id`),
  KEY `ix_product_roles_product_id` (`product_id`),
  KEY `ix_product_roles_role_id` (`role_id`),
  CONSTRAINT `fk_product_roles_product`
    FOREIGN KEY (`product_id`) REFERENCES `products` (`product_id`)
    ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT `fk_product_roles_role`
    FOREIGN KEY (`role_id`) REFERENCES `roles` (`role_id`)
    ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE `user_product_map` (
  `user_product_map_id` int NOT NULL AUTO_INCREMENT,
  `product_id` varchar(45) NOT NULL,
  `user_id` varchar(45) NOT NULL,
  PRIMARY KEY (`user_product_map_id`),
  UNIQUE KEY `user_product_map_id_UNIQUE` (`user_product_map_id`),
  KEY `fk_product_idx` (`product_id`),
  KEY `fk_user_idx` (`user_id`),
  CONSTRAINT `fk_user_product_map_product`
    FOREIGN KEY (`product_id`) REFERENCES `products` (`product_id`)
    ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT `fk_user_product_map_user`
    FOREIGN KEY (`user_id`) REFERENCES `users` (`user_id`)
    ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB AUTO_INCREMENT=199 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE `user_roles` (
  `user_role_id` int NOT NULL AUTO_INCREMENT,
  `user_id` varchar(45) NOT NULL,
  `product_role_id` varchar(45) NOT NULL,
  PRIMARY KEY (`user_role_id`),
  KEY `ix_user_roles_user_id` (`user_id`),
  KEY `ix_user_roles_product_role_id` (`product_role_id`),
  CONSTRAINT `fk_user_roles_user`
    FOREIGN KEY (`user_id`) REFERENCES `users` (`user_id`)
    ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT `fk_user_roles_product_role`
    FOREIGN KEY (`product_role_id`) REFERENCES `product_roles` (`product_role_id`)
    ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB AUTO_INCREMENT=245 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE `user_workspace_map` (
  `user_organization_map_id` int NOT NULL AUTO_INCREMENT,
  `user_id` varchar(45) NOT NULL,
  `workspace_id` varchar(45) NOT NULL,
  `is_default` tinyint NOT NULL,
  PRIMARY KEY (`user_organization_map_id`),
  UNIQUE KEY `user_organization_map_id_UNIQUE` (`user_organization_map_id`),
  KEY `user_id_idx` (`user_id`),
  CONSTRAINT `fk_user_workspace_map_user`
    FOREIGN KEY (`user_id`) REFERENCES `users` (`user_id`)
    ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB AUTO_INCREMENT=194 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;