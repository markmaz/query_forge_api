-- V010__sales_inquiry.sql
-- Public sales inquiry submissions

CREATE TABLE `sales_inquiry` (
  `id` binary(16) NOT NULL COMMENT 'UUID (binary)',
  `first_name` varchar(255) NOT NULL,
  `last_name` varchar(255) NOT NULL,
  `work_email` varchar(320) NOT NULL,
  `phone` varchar(32) DEFAULT NULL,
  `organization` varchar(255) NOT NULL,
  `role_title` varchar(255) NOT NULL,
  `primary_interest` varchar(128) NOT NULL,
  `primary_data_model` varchar(128) NOT NULL,
  `problem_statement` text NOT NULL,
  `consent_contact` tinyint(1) NOT NULL,
  `source` varchar(64) DEFAULT NULL,
  `ip_address` varchar(45) DEFAULT NULL,
  `user_agent` varchar(255) DEFAULT NULL,
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` timestamp NULL DEFAULT NULL ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `ix_sales_inquiry_created_at` (`created_at`),
  KEY `ix_sales_inquiry_work_email` (`work_email`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
