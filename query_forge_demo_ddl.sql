-- MySQL dump 10.13  Distrib 9.5.0, for macos15.7 (arm64)
--
-- Host: localhost    Database: query_forge_demo
-- ------------------------------------------------------
-- Server version	9.5.0

/*!40101 SET @OLD_CHARACTER_SET_CLIENT=@@CHARACTER_SET_CLIENT */;
/*!40101 SET @OLD_CHARACTER_SET_RESULTS=@@CHARACTER_SET_RESULTS */;
/*!40101 SET @OLD_COLLATION_CONNECTION=@@COLLATION_CONNECTION */;
/*!50503 SET NAMES utf8mb4 */;
/*!40103 SET @OLD_TIME_ZONE=@@TIME_ZONE */;
/*!40103 SET TIME_ZONE='+00:00' */;
/*!40014 SET @OLD_UNIQUE_CHECKS=@@UNIQUE_CHECKS, UNIQUE_CHECKS=0 */;
/*!40014 SET @OLD_FOREIGN_KEY_CHECKS=@@FOREIGN_KEY_CHECKS, FOREIGN_KEY_CHECKS=0 */;
/*!40101 SET @OLD_SQL_MODE=@@SQL_MODE, SQL_MODE='NO_AUTO_VALUE_ON_ZERO' */;
/*!40111 SET @OLD_SQL_NOTES=@@SQL_NOTES, SQL_NOTES=0 */;

--
-- Table structure for table `__ddl_lock`
--

DROP TABLE IF EXISTS `__ddl_lock`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `__ddl_lock` (
  `id` tinyint NOT NULL,
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `crosswalk_list_meta`
--

DROP TABLE IF EXISTS `crosswalk_list_meta`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `crosswalk_list_meta` (
  `id` char(36) NOT NULL,
  `workspace_id` varchar(64) NOT NULL,
  `list_type` varchar(32) NOT NULL,
  `list_id` char(36) NOT NULL,
  `list_name` varchar(255) NOT NULL,
  `user_id` varchar(255) DEFAULT NULL,
  `user_name` varchar(255) DEFAULT NULL,
  `is_shared` tinyint(1) NOT NULL DEFAULT '0',
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_cwlm_ws_type_listid` (`workspace_id`,`list_type`,`list_id`),
  KEY `ix_cwlm_ws_type` (`workspace_id`,`list_type`),
  KEY `ix_cwlm_ws_shared` (`workspace_id`,`is_shared`),
  KEY `ix_cwlm_ws_user` (`workspace_id`,`user_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `datasource`
--

DROP TABLE IF EXISTS `datasource`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `datasource` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT,
  `organization_id` varchar(128) NOT NULL,
  `name` varchar(255) NOT NULL,
  `slug` varchar(255) NOT NULL,
  `type` varchar(32) NOT NULL,
  `description` text,
  `is_active` tinyint(1) NOT NULL DEFAULT '1',
  `secret_ref` varchar(512) DEFAULT NULL,
  `config_json` json DEFAULT NULL,
  `last_tested_at` datetime DEFAULT NULL,
  `last_test_status` varchar(32) DEFAULT NULL,
  `last_test_message` varchar(1000) DEFAULT NULL,
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` timestamp NULL DEFAULT NULL ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_datasource_org_slug` (`organization_id`,`slug`),
  UNIQUE KEY `uq_datasource_org_name` (`organization_id`,`name`),
  KEY `ix_datasource_org` (`organization_id`),
  KEY `ix_datasource_type` (`type`),
  KEY `ix_datasource_active` (`organization_id`,`is_active`),
  KEY `ix_datasource_test_status` (`last_test_status`),
  CONSTRAINT `fk_datasource_org` FOREIGN KEY (`organization_id`) REFERENCES `organization` (`id`) ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT `chk_datasource_type` CHECK ((`type` in (_utf8mb4'databricks',_utf8mb4'snowflake',_utf8mb4'mysql',_utf8mb4'postgres',_utf8mb4'bigquery')))
) ENGINE=InnoDB AUTO_INCREMENT=2 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `domain`
--

DROP TABLE IF EXISTS `domain`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `domain` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT,
  `workspace_id` varchar(128) NOT NULL,
  `name` varchar(255) NOT NULL,
  `kind` text,
  `description` text,
  `is_active` tinyint(1) NOT NULL DEFAULT '1',
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` timestamp NULL DEFAULT NULL ON UPDATE CURRENT_TIMESTAMP,
  `model_table_id` bigint unsigned DEFAULT NULL,
  `column_name_policy` enum('DEDUP_PRIMARY_FIRST','SHOW_ALL_QUALIFIED') NOT NULL DEFAULT 'DEDUP_PRIMARY_FIRST',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_domain_ws_name` (`workspace_id`,`name`),
  KEY `ix_domain_ws` (`workspace_id`),
  KEY `ix_domain_model_table_id` (`model_table_id`),
  KEY `ix_domain_column_name_policy` (`column_name_policy`),
  CONSTRAINT `fk_domain_model_table` FOREIGN KEY (`model_table_id`) REFERENCES `model_table` (`id`) ON DELETE RESTRICT ON UPDATE CASCADE,
  CONSTRAINT `fk_domain_ws` FOREIGN KEY (`workspace_id`) REFERENCES `workspace` (`id`) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB AUTO_INCREMENT=5 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `domain_embedding_state`
--

DROP TABLE IF EXISTS `domain_embedding_state`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `domain_embedding_state` (
  `domain_id` bigint unsigned NOT NULL,
  `workspace_id` varchar(64) DEFAULT NULL,
  `vertical_norm` varchar(50) NOT NULL DEFAULT 'generic',
  `domain_version` int NOT NULL,
  `embedding_hash` char(64) NOT NULL,
  `indexed_at` datetime NOT NULL,
  PRIMARY KEY (`domain_id`),
  KEY `idx_domain_embedding_state_vertical` (`vertical_norm`),
  KEY `idx_domain_embedding_state_ws` (`workspace_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `domain_profile`
--

DROP TABLE IF EXISTS `domain_profile`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `domain_profile` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT,
  `workspace_id` varchar(128) NOT NULL,
  `domain_id` bigint unsigned NOT NULL,
  `summary` text,
  `keywords` json DEFAULT NULL,
  `entities` json DEFAULT NULL,
  `metrics` json DEFAULT NULL,
  `synonyms` json DEFAULT NULL,
  `acronyms` json DEFAULT NULL,
  `notes` text,
  `embedding_text` mediumtext NOT NULL,
  `content_hash` char(64) NOT NULL,
  `embedding_model` varchar(128) DEFAULT NULL,
  `embedded_at` timestamp NULL DEFAULT NULL,
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` timestamp NULL DEFAULT NULL ON UPDATE CURRENT_TIMESTAMP,
  `attributes` json DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_domain_profile` (`workspace_id`,`domain_id`),
  KEY `ix_domain_profile_ws` (`workspace_id`),
  KEY `ix_domain_profile_domain` (`domain_id`),
  CONSTRAINT `fk_domain_profile_domain` FOREIGN KEY (`domain_id`) REFERENCES `domain` (`id`) ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT `fk_domain_profile_ws` FOREIGN KEY (`workspace_id`) REFERENCES `workspace` (`id`) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB AUTO_INCREMENT=8 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `domain_table_join`
--

DROP TABLE IF EXISTS `domain_table_join`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `domain_table_join` (
  `id` char(36) NOT NULL DEFAULT (uuid()),
  `domain_id` bigint unsigned NOT NULL,
  `from_workspace_table_id` bigint unsigned NOT NULL,
  `to_workspace_table_id` bigint unsigned NOT NULL,
  `join_type` enum('INNER','LEFT','RIGHT') NOT NULL DEFAULT 'LEFT',
  `join_spec_json` json NOT NULL,
  `sort_order` int NOT NULL DEFAULT '0',
  `is_active` tinyint(1) NOT NULL DEFAULT '1',
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` timestamp NULL DEFAULT NULL ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_dtj_edge` (`domain_id`,`from_workspace_table_id`,`to_workspace_table_id`,`sort_order`),
  KEY `ix_dtj_domain` (`domain_id`),
  KEY `ix_dtj_from` (`domain_id`,`from_workspace_table_id`),
  KEY `ix_dtj_to` (`domain_id`,`to_workspace_table_id`),
  KEY `ix_dtj_domain_sort` (`domain_id`,`sort_order`),
  KEY `fk_dtj_from_wst` (`from_workspace_table_id`),
  KEY `fk_dtj_to_wst` (`to_workspace_table_id`),
  CONSTRAINT `fk_dtj_domain` FOREIGN KEY (`domain_id`) REFERENCES `domain` (`id`) ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT `fk_dtj_from_wst` FOREIGN KEY (`from_workspace_table_id`) REFERENCES `workspace_table` (`id`) ON DELETE RESTRICT ON UPDATE CASCADE,
  CONSTRAINT `fk_dtj_to_wst` FOREIGN KEY (`to_workspace_table_id`) REFERENCES `workspace_table` (`id`) ON DELETE RESTRICT ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `domain_time_policy`
--

DROP TABLE IF EXISTS `domain_time_policy`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `domain_time_policy` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT,
  `workspace_id` varchar(128) NOT NULL,
  `domain_id` bigint unsigned NOT NULL,
  `calendar_mode` varchar(16) NOT NULL DEFAULT 'calendar',
  `fiscal_year_start_month` tinyint unsigned DEFAULT NULL,
  `timezone` varchar(64) DEFAULT NULL,
  `week_start` varchar(16) NOT NULL DEFAULT 'monday',
  `default_time_concept_key` varchar(128) DEFAULT NULL,
  `allow_relative_ranges` tinyint(1) NOT NULL DEFAULT '1',
  `default_grain` varchar(16) DEFAULT NULL,
  `prefer_time_object_over_filter` tinyint(1) NOT NULL DEFAULT '1',
  `strict_mode` tinyint(1) NOT NULL DEFAULT '1',
  `relative_map` json DEFAULT NULL,
  `notes` text,
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` timestamp NULL DEFAULT NULL ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_domain_time_policy` (`workspace_id`,`domain_id`),
  KEY `ix_domain_time_policy_domain` (`domain_id`),
  CONSTRAINT `fk_domain_time_policy_domain` FOREIGN KEY (`domain_id`) REFERENCES `domain` (`id`) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB AUTO_INCREMENT=3 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `domain_workspace_table`
--

DROP TABLE IF EXISTS `domain_workspace_table`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `domain_workspace_table` (
  `domain_id` bigint unsigned NOT NULL,
  `workspace_table_id` bigint unsigned NOT NULL,
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `role` varchar(64) DEFAULT NULL,
  `is_primary` tinyint(1) NOT NULL DEFAULT '0',
  `relation_kind` enum('JOIN','UNION') NOT NULL DEFAULT 'JOIN',
  `sort_order` int NOT NULL DEFAULT '0',
  `table_alias` varchar(64) DEFAULT NULL,
  `filter_mode` enum('AUTO','WHERE','EXISTS') NOT NULL DEFAULT 'AUTO',
  `cardinality` enum('ONE','MANY') NOT NULL DEFAULT 'ONE',
  `primary_key_once` tinyint GENERATED ALWAYS AS (if((`is_primary` = 1),1,NULL)) STORED,
  PRIMARY KEY (`domain_id`,`workspace_table_id`),
  UNIQUE KEY `uq_dwt_one_primary_per_domain` (`domain_id`,`primary_key_once`),
  KEY `ix_dwt_wst` (`workspace_table_id`),
  KEY `ix_dwt_domain_sort` (`domain_id`,`sort_order`),
  KEY `ix_dwt_domain_filter_mode` (`domain_id`,`filter_mode`),
  KEY `ix_dwt_domain_cardinality` (`domain_id`,`cardinality`),
  CONSTRAINT `fk_dwt_domain` FOREIGN KEY (`domain_id`) REFERENCES `domain` (`id`) ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT `fk_dwt_wst` FOREIGN KEY (`workspace_table_id`) REFERENCES `workspace_table` (`id`) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `forge_insights_conversation`
--

DROP TABLE IF EXISTS `forge_insights_conversation`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `forge_insights_conversation` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT,
  `workspace_id` varchar(64) NOT NULL,
  `user_id` varchar(255) NOT NULL,
  `conversation_id` varchar(128) NOT NULL,
  `title` varchar(255) DEFAULT NULL,
  `summary` longtext,
  `message_count` int unsigned NOT NULL DEFAULT '0',
  `last_message_at` datetime DEFAULT NULL,
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_fic_workspace_user_conversation` (`workspace_id`,`user_id`,`conversation_id`),
  KEY `idx_fic_workspace_user_updated` (`workspace_id`,`user_id`,`updated_at`),
  KEY `idx_fic_workspace_user_last` (`workspace_id`,`user_id`,`last_message_at`)
) ENGINE=InnoDB AUTO_INCREMENT=3 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `forge_insights_message`
--

DROP TABLE IF EXISTS `forge_insights_message`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `forge_insights_message` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT,
  `conversation_pk` bigint unsigned NOT NULL,
  `seq_no` int unsigned NOT NULL,
  `role` enum('user','assistant','system') NOT NULL,
  `content` longtext NOT NULL,
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_fim_conversation_seq` (`conversation_pk`,`seq_no`,`id`),
  CONSTRAINT `fk_fim_conversation` FOREIGN KEY (`conversation_pk`) REFERENCES `forge_insights_conversation` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `forge_insights_project`
--

DROP TABLE IF EXISTS `forge_insights_project`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `forge_insights_project` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT,
  `workspace_id` varchar(64) NOT NULL,
  `user_id` varchar(255) NOT NULL,
  `name` varchar(255) NOT NULL,
  `description` text,
  `is_archived` tinyint(1) NOT NULL DEFAULT '0',
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_fip_workspace_user_updated` (`workspace_id`,`user_id`,`updated_at`),
  KEY `idx_fip_workspace_user_archived` (`workspace_id`,`user_id`,`is_archived`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `forge_insights_thread`
--

DROP TABLE IF EXISTS `forge_insights_thread`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `forge_insights_thread` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT,
  `workspace_id` varchar(64) NOT NULL,
  `user_id` varchar(255) NOT NULL,
  `project_id` bigint unsigned DEFAULT NULL,
  `conversation_id` varchar(128) NOT NULL,
  `title` varchar(255) DEFAULT NULL,
  `preview_text` text,
  `is_pinned` tinyint(1) NOT NULL DEFAULT '0',
  `is_archived` tinyint(1) NOT NULL DEFAULT '0',
  `last_message_at` datetime DEFAULT NULL,
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_fit_workspace_user_conversation` (`workspace_id`,`user_id`,`conversation_id`),
  KEY `idx_fit_workspace_user_last` (`workspace_id`,`user_id`,`last_message_at`),
  KEY `idx_fit_workspace_user_updated` (`workspace_id`,`user_id`,`updated_at`),
  KEY `idx_fit_project_updated` (`project_id`,`updated_at`),
  CONSTRAINT `fk_fit_project` FOREIGN KEY (`project_id`) REFERENCES `forge_insights_project` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `forge_match_result`
--

DROP TABLE IF EXISTS `forge_match_result`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `forge_match_result` (
  `id` char(36) NOT NULL,
  `session_id` char(36) NOT NULL,
  `source_record_id` bigint unsigned NOT NULL,
  `best_match_workspace_column_id` bigint unsigned DEFAULT NULL,
  `alternate_workspace_column_ids` json DEFAULT NULL,
  `retrieved_candidates_json` json DEFAULT NULL,
  `llm_response_json` json DEFAULT NULL,
  `match_decision` varchar(32) NOT NULL DEFAULT 'no_confident_match',
  `reason_codes_json` json DEFAULT NULL,
  `explanation` text,
  `ambiguity_note` text,
  `llm_confidence` decimal(5,4) DEFAULT NULL,
  `confidence_score` int NOT NULL DEFAULT '0',
  `confidence_band` varchar(16) NOT NULL DEFAULT 'low',
  `status` varchar(32) NOT NULL DEFAULT 'suggested',
  `review_notes` text,
  `manually_selected_workspace_column_id` bigint unsigned DEFAULT NULL,
  `reviewer_user_id` varchar(255) DEFAULT NULL,
  `reviewed_at` datetime DEFAULT NULL,
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` timestamp NULL DEFAULT NULL ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_forge_match_result_session_source` (`session_id`,`source_record_id`),
  KEY `idx_forge_match_result_session_status` (`session_id`,`status`),
  KEY `idx_forge_match_result_best_column` (`best_match_workspace_column_id`),
  KEY `idx_forge_match_result_manual_column` (`manually_selected_workspace_column_id`),
  KEY `fk_forge_match_result_source` (`source_record_id`),
  CONSTRAINT `fk_forge_match_result_best_column` FOREIGN KEY (`best_match_workspace_column_id`) REFERENCES `workspace_column` (`id`) ON DELETE SET NULL ON UPDATE CASCADE,
  CONSTRAINT `fk_forge_match_result_manual_column` FOREIGN KEY (`manually_selected_workspace_column_id`) REFERENCES `workspace_column` (`id`) ON DELETE SET NULL ON UPDATE CASCADE,
  CONSTRAINT `fk_forge_match_result_session` FOREIGN KEY (`session_id`) REFERENCES `forge_match_session` (`id`) ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT `fk_forge_match_result_source` FOREIGN KEY (`source_record_id`) REFERENCES `forge_match_source_record` (`id`) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `forge_match_session`
--

DROP TABLE IF EXISTS `forge_match_session`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `forge_match_session` (
  `id` char(36) NOT NULL,
  `workspace_id` varchar(128) NOT NULL,
  `uploaded_filename` varchar(512) NOT NULL,
  `file_type` varchar(16) NOT NULL,
  `created_by` varchar(255) NOT NULL,
  `status` varchar(32) NOT NULL DEFAULT 'uploaded',
  `sheet_count` int NOT NULL DEFAULT '0',
  `source_record_count` int NOT NULL DEFAULT '0',
  `analysis_started_at` datetime DEFAULT NULL,
  `analysis_completed_at` datetime DEFAULT NULL,
  `summary_json` json DEFAULT NULL,
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` timestamp NULL DEFAULT NULL ON UPDATE CURRENT_TIMESTAMP,
  `analysis_job_id` char(36) DEFAULT NULL,
  `current_phase` varchar(64) DEFAULT NULL,
  `current_source_row_id` varchar(128) DEFAULT NULL,
  `analyzed_count` int NOT NULL DEFAULT '0',
  `skipped_count` int NOT NULL DEFAULT '0',
  `failed_count` int NOT NULL DEFAULT '0',
  `cancel_requested` tinyint(1) NOT NULL DEFAULT '0',
  `analysis_error` text,
  `last_heartbeat_at` datetime DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `idx_forge_match_session_workspace_created` (`workspace_id`,`created_at`),
  KEY `idx_forge_match_session_status` (`status`),
  KEY `idx_forge_match_session_analysis_job` (`analysis_job_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `forge_match_source_record`
--

DROP TABLE IF EXISTS `forge_match_source_record`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `forge_match_source_record` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT,
  `session_id` char(36) NOT NULL,
  `row_id` varchar(128) NOT NULL,
  `sheet_name` varchar(255) DEFAULT NULL,
  `row_number` int DEFAULT NULL,
  `source_field_name` varchar(255) NOT NULL,
  `source_description` text,
  `source_type` varchar(100) DEFAULT NULL,
  `source_object_name` varchar(255) DEFAULT NULL,
  `sample_value` text,
  `category` varchar(255) DEFAULT NULL,
  `normalized_search_text` text,
  `raw_row_json` json DEFAULT NULL,
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_forge_match_source_session_row` (`session_id`,`row_id`),
  KEY `idx_forge_match_source_session_name` (`session_id`,`source_field_name`),
  CONSTRAINT `fk_forge_match_source_session` FOREIGN KEY (`session_id`) REFERENCES `forge_match_session` (`id`) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB AUTO_INCREMENT=676 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `ingestion_run`
--

DROP TABLE IF EXISTS `ingestion_run`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `ingestion_run` (
  `id` varchar(36) NOT NULL,
  `datasource` varchar(100) NOT NULL,
  `catalog` varchar(200) DEFAULT NULL,
  `schema_name` varchar(200) NOT NULL,
  `table_names` json DEFAULT NULL,
  `run_profiling` tinyint(1) NOT NULL DEFAULT '0',
  `run_enrichment` tinyint(1) NOT NULL DEFAULT '0',
  `status` varchar(20) NOT NULL DEFAULT 'running',
  `tables_total` int NOT NULL DEFAULT '0',
  `tables_done` int NOT NULL DEFAULT '0',
  `tables_failed` int NOT NULL DEFAULT '0',
  `tables_created` int NOT NULL DEFAULT '0',
  `tables_updated` int NOT NULL DEFAULT '0',
  `columns_total` int NOT NULL DEFAULT '0',
  `columns_done` int NOT NULL DEFAULT '0',
  `columns_failed` int NOT NULL DEFAULT '0',
  `columns_created` int NOT NULL DEFAULT '0',
  `columns_updated` int NOT NULL DEFAULT '0',
  `current_phase` varchar(50) DEFAULT NULL,
  `current_table` varchar(255) DEFAULT NULL,
  `current_column` varchar(255) DEFAULT NULL,
  `error` text,
  `started_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `completed_at` datetime DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `idx_ingestion_run_started_at` (`started_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `model_column`
--

DROP TABLE IF EXISTS `model_column`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `model_column` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT,
  `model_table_id` bigint unsigned NOT NULL,
  `column_name` varchar(255) NOT NULL,
  `data_type` longtext,
  `description` longtext,
  `semantic_type` varchar(100) DEFAULT NULL,
  `ordinal_position` int NOT NULL DEFAULT '0',
  `nullable` tinyint(1) NOT NULL DEFAULT '1',
  `is_active` tinyint(1) NOT NULL DEFAULT '1',
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` timestamp NULL DEFAULT NULL ON UPDATE CURRENT_TIMESTAMP,
  `sample_values_json` longtext,
  `sample_stats_json` longtext,
  `sample_ran_at` timestamp NULL DEFAULT NULL,
  `sample_error` varchar(500) DEFAULT NULL,
  `origin` varchar(16) NOT NULL DEFAULT 'DBX',
  `is_missing_in_source` tinyint(1) NOT NULL DEFAULT '0',
  `semantic_concept_id` bigint unsigned DEFAULT NULL,
  `semantic_concept_key` varchar(150) DEFAULT NULL,
  `semantic_entity` varchar(100) DEFAULT NULL,
  `semantic_sub_type` varchar(200) DEFAULT NULL,
  `semantic_granularity_rank` int NOT NULL DEFAULT '0',
  `semantic_source` varchar(20) DEFAULT NULL,
  `semantic_confidence` decimal(4,3) DEFAULT NULL,
  `semantic_reasons_json` longtext,
  `semantic_warnings_json` longtext,
  `semantic_updated_at` datetime DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_model_col` (`model_table_id`,`column_name`),
  KEY `ix_model_col_name` (`column_name`),
  KEY `ix_model_col_missing` (`is_missing_in_source`),
  KEY `ix_model_col_origin` (`origin`),
  KEY `idx_model_column_semantic_concept_id` (`semantic_concept_id`),
  KEY `idx_model_column_semantic_concept_key` (`semantic_concept_key`),
  KEY `idx_model_column_table_semantic_key` (`model_table_id`,`semantic_concept_key`),
  CONSTRAINT `fk_model_col_table` FOREIGN KEY (`model_table_id`) REFERENCES `model_table` (`id`) ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT `fk_model_column_semantic_concept` FOREIGN KEY (`semantic_concept_id`) REFERENCES `semantic_concept` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB AUTO_INCREMENT=931 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `model_column_semantic_concept_map`
--

DROP TABLE IF EXISTS `model_column_semantic_concept_map`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `model_column_semantic_concept_map` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT,
  `vertical_norm` varchar(50) NOT NULL DEFAULT 'generic',
  `semantic_concept_id` bigint unsigned NOT NULL,
  `model_column_id` bigint unsigned NOT NULL,
  `relationship_kind` varchar(30) NOT NULL DEFAULT 'primary',
  `weight` decimal(4,3) NOT NULL DEFAULT '1.000',
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_map` (`vertical_norm`,`semantic_concept_id`,`model_column_id`,`relationship_kind`),
  KEY `idx_map_concept` (`vertical_norm`,`semantic_concept_id`),
  KEY `idx_map_column` (`model_column_id`),
  KEY `fk_map_concept` (`semantic_concept_id`),
  CONSTRAINT `fk_map_column` FOREIGN KEY (`model_column_id`) REFERENCES `model_column` (`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_map_concept` FOREIGN KEY (`semantic_concept_id`) REFERENCES `semantic_concept` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `model_table`
--

DROP TABLE IF EXISTS `model_table`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `model_table` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT,
  `name` varchar(255) NOT NULL,
  `source_table_name` varchar(255) DEFAULT NULL,
  `description` text,
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` timestamp NULL DEFAULT NULL ON UPDATE CURRENT_TIMESTAMP,
  `origin` varchar(16) NOT NULL DEFAULT 'DBX',
  `is_missing_in_source` tinyint(1) NOT NULL DEFAULT '0',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_model_table_name` (`name`),
  UNIQUE KEY `uq_model_table_source_table_name` (`source_table_name`),
  KEY `ix_model_table_source_table_name` (`source_table_name`),
  KEY `ix_model_tbl_missing` (`is_missing_in_source`),
  KEY `ix_model_tbl_origin` (`origin`)
) ENGINE=InnoDB AUTO_INCREMENT=81 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `organization`
--

DROP TABLE IF EXISTS `organization`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `organization` (
  `id` varchar(128) NOT NULL,
  `name` varchar(255) NOT NULL,
  `slug` varchar(255) NOT NULL,
  `description` text,
  `is_active` tinyint(1) NOT NULL DEFAULT '1',
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` timestamp NULL DEFAULT NULL ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_organization_slug` (`slug`),
  KEY `ix_organization_name` (`name`),
  KEY `ix_organization_active` (`is_active`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `organization_membership`
--

DROP TABLE IF EXISTS `organization_membership`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `organization_membership` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT,
  `organization_id` varchar(128) NOT NULL,
  `user_id` varchar(255) NOT NULL,
  `role` varchar(64) NOT NULL DEFAULT 'member',
  `is_active` tinyint(1) NOT NULL DEFAULT '1',
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` timestamp NULL DEFAULT NULL ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_org_membership` (`organization_id`,`user_id`),
  KEY `ix_org_membership_user` (`user_id`),
  KEY `ix_org_membership_org_role` (`organization_id`,`role`),
  KEY `ix_org_membership_active` (`organization_id`,`is_active`),
  CONSTRAINT `fk_org_membership_org` FOREIGN KEY (`organization_id`) REFERENCES `organization` (`id`) ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT `fk_org_membership_user` FOREIGN KEY (`user_id`) REFERENCES `users` (`user_id`) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB AUTO_INCREMENT=2 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `planner_cache`
--

DROP TABLE IF EXISTS `planner_cache`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `planner_cache` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT,
  `cache_key` char(64) NOT NULL,
  `workspace_id` varchar(64) NOT NULL,
  `vertical` varchar(32) NOT NULL DEFAULT 'generic',
  `normalized_prompt` text NOT NULL,
  `constraints_json` longtext NOT NULL,
  `registry_version` varchar(64) NOT NULL,
  `plan_json` longtext NOT NULL,
  `sql_json` longtext NOT NULL,
  `validation_json` longtext NOT NULL,
  `candidates_json` longtext,
  `expires_at` datetime NOT NULL,
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `ux_planner_cache_key` (`cache_key`),
  KEY `idx_planner_cache_lookup` (`workspace_id`,`vertical`,`registry_version`,`expires_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `product_group_map`
--

DROP TABLE IF EXISTS `product_group_map`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `product_group_map` (
  `product_group_map_id` varchar(40) NOT NULL,
  `product_id` varchar(45) NOT NULL,
  `product_group_id` varchar(45) NOT NULL,
  PRIMARY KEY (`product_group_map_id`),
  KEY `ix_pgm_product_id` (`product_id`),
  KEY `ix_pgm_product_group_id` (`product_group_id`),
  CONSTRAINT `fk_pgm_product` FOREIGN KEY (`product_id`) REFERENCES `products` (`product_id`) ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT `fk_pgm_product_group` FOREIGN KEY (`product_group_id`) REFERENCES `product_groups` (`product_group_id`) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `product_groups`
--

DROP TABLE IF EXISTS `product_groups`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `product_groups` (
  `product_group_id` varchar(45) NOT NULL,
  `product_group_name` varchar(100) NOT NULL,
  `status` varchar(45) NOT NULL DEFAULT 'Active',
  `last_update` datetime DEFAULT NULL,
  PRIMARY KEY (`product_group_id`),
  UNIQUE KEY `product_group_id_UNIQUE` (`product_group_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `products`
--

DROP TABLE IF EXISTS `products`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `products` (
  `product_id` varchar(45) NOT NULL,
  `product_name` varchar(45) NOT NULL,
  `status` varchar(45) NOT NULL DEFAULT 'Active',
  `last_update` datetime DEFAULT NULL,
  `product_group_id` varchar(45) DEFAULT NULL,
  PRIMARY KEY (`product_id`),
  UNIQUE KEY `product_id_UNIQUE` (`product_id`),
  KEY `ix_products_product_group_id` (`product_group_id`),
  CONSTRAINT `fk_products_product_group` FOREIGN KEY (`product_group_id`) REFERENCES `product_groups` (`product_group_id`) ON DELETE SET NULL ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `prompt_feedback`
--

DROP TABLE IF EXISTS `prompt_feedback`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `prompt_feedback` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT,
  `workspace_id` varchar(64) NOT NULL,
  `user_id` varchar(255) NOT NULL,
  `trace_id` varchar(64) DEFAULT NULL,
  `vote` enum('up','down') NOT NULL,
  `normalized_prompt` text,
  `prompt_text` text,
  `response_json` json NOT NULL,
  `meta_json` json DEFAULT NULL,
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_pf_workspace_user_trace` (`workspace_id`,`user_id`,`trace_id`),
  KEY `idx_pf_workspace_user_created` (`workspace_id`,`user_id`,`created_at`),
  KEY `idx_pf_trace` (`trace_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `query_skills`
--

DROP TABLE IF EXISTS `query_skills`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `query_skills` (
  `id` char(36) NOT NULL,
  `workspace_id` varchar(128) NOT NULL,
  `name` varchar(255) NOT NULL,
  `skill_type` varchar(64) NOT NULL,
  `query_id` char(36) DEFAULT NULL,
  `config_json` json DEFAULT NULL,
  `is_active` tinyint NOT NULL DEFAULT '1',
  `created_by` varchar(255) NOT NULL,
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` timestamp NULL DEFAULT NULL ON UPDATE CURRENT_TIMESTAMP,
  `last_alert_state` json DEFAULT NULL COMMENT 'Stores last evaluated condition results for threshold_alert on_change mode.',
  `alert_acknowledged_at` datetime DEFAULT NULL COMMENT 'Set when a user manually acknowledges an alert. Cleared on next state change.',
  `is_shared` tinyint(1) NOT NULL DEFAULT '0' COMMENT '1 = any workspace member with skills:user can read this skill',
  PRIMARY KEY (`id`),
  KEY `idx_query_skills_workspace_active` (`workspace_id`,`is_active`),
  KEY `idx_query_skills_skill_type` (`skill_type`),
  KEY `ix_query_skills_shared` (`workspace_id`,`is_shared`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `roles`
--

DROP TABLE IF EXISTS `roles`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `roles` (
  `id` int NOT NULL AUTO_INCREMENT,
  `name` varchar(64) NOT NULL,
  `display_name` varchar(128) NOT NULL,
  `description` varchar(500) DEFAULT NULL,
  `feature_key` varchar(64) DEFAULT NULL COMMENT 'NULL for global roles (super_admin, workspace_admin)',
  `is_system` tinyint(1) NOT NULL DEFAULT '1' COMMENT 'System roles cannot be deleted via API',
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_roles_name` (`name`)
) ENGINE=InnoDB AUTO_INCREMENT=29 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `sales_inquiry`
--

DROP TABLE IF EXISTS `sales_inquiry`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
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
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `saved_query`
--

DROP TABLE IF EXISTS `saved_query`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `saved_query` (
  `id` char(36) NOT NULL DEFAULT (uuid()),
  `scope` varchar(16) NOT NULL,
  `workspace_id` varchar(128) DEFAULT NULL,
  `owner_user_id` char(36) DEFAULT NULL,
  `folder_id` char(36) DEFAULT NULL,
  `title` varchar(255) NOT NULL,
  `description` text,
  `sql_json` longtext NOT NULL,
  `updated_by` char(36) DEFAULT NULL,
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  `is_deleted` tinyint(1) NOT NULL DEFAULT '0',
  `deleted_at` timestamp NULL DEFAULT NULL,
  `deleted_by_user_id` char(36) DEFAULT NULL,
  `created_by` varchar(255) DEFAULT NULL COMMENT 'User who created this query. NULL = legacy, migrated to system user.',
  `is_shared` tinyint(1) NOT NULL DEFAULT '0' COMMENT '1 = any workspace member with query_studio:user can read this query',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_sq_title_in_folder` (`scope`,`workspace_id`,`owner_user_id`,`folder_id`,`title`),
  KEY `idx_sq_lookup_mine` (`workspace_id`,`owner_user_id`,`scope`,`updated_at`),
  KEY `idx_sq_lookup_scope` (`scope`,`updated_at`),
  KEY `idx_sq_folder` (`folder_id`,`updated_at`),
  KEY `idx_sq_active_lookup` (`workspace_id`,`scope`,`owner_user_id`,`is_deleted`,`updated_at`),
  KEY `idx_sq_trash_lookup` (`workspace_id`,`scope`,`owner_user_id`,`is_deleted`,`deleted_at`),
  KEY `idx_sq_deleted_at` (`is_deleted`,`deleted_at`),
  KEY `ix_saved_query_created_by` (`created_by`,`workspace_id`),
  KEY `ix_saved_query_shared` (`workspace_id`,`is_shared`),
  CONSTRAINT `fk_saved_query_created_by` FOREIGN KEY (`created_by`) REFERENCES `users` (`user_id`) ON DELETE SET NULL,
  CONSTRAINT `fk_sq_folder` FOREIGN KEY (`folder_id`) REFERENCES `saved_query_folder` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `saved_query_acl`
--

DROP TABLE IF EXISTS `saved_query_acl`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `saved_query_acl` (
  `id` char(36) NOT NULL DEFAULT (uuid()),
  `saved_query_id` char(36) NOT NULL,
  `workspace_id` varchar(128) NOT NULL,
  `principal_type` varchar(16) NOT NULL,
  `principal_id` varchar(128) NOT NULL,
  `permission` varchar(16) NOT NULL,
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_sqa_unique` (`saved_query_id`,`principal_type`,`principal_id`),
  KEY `idx_sqa_principal` (`workspace_id`,`principal_type`,`principal_id`,`permission`),
  CONSTRAINT `fk_sqa_query` FOREIGN KEY (`saved_query_id`) REFERENCES `saved_query` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `saved_query_folder`
--

DROP TABLE IF EXISTS `saved_query_folder`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `saved_query_folder` (
  `id` char(36) NOT NULL DEFAULT (uuid()),
  `scope` varchar(16) NOT NULL,
  `workspace_id` varchar(128) DEFAULT NULL,
  `owner_user_id` char(36) DEFAULT NULL,
  `parent_id` char(36) DEFAULT NULL,
  `name` varchar(255) NOT NULL,
  `sort_index` int NOT NULL DEFAULT '0',
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  `is_deleted` tinyint(1) NOT NULL DEFAULT '0',
  `deleted_at` timestamp NULL DEFAULT NULL,
  `deleted_by_user_id` char(36) DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_sqf_sibling_name` (`scope`,`workspace_id`,`owner_user_id`,`parent_id`,`name`),
  KEY `idx_sqf_lookup` (`workspace_id`,`scope`,`owner_user_id`),
  KEY `idx_sqf_parent` (`parent_id`),
  KEY `idx_sqf_active_lookup` (`workspace_id`,`scope`,`owner_user_id`,`is_deleted`,`updated_at`),
  KEY `idx_sqf_trash_lookup` (`workspace_id`,`scope`,`owner_user_id`,`is_deleted`,`deleted_at`),
  CONSTRAINT `fk_sqf_parent` FOREIGN KEY (`parent_id`) REFERENCES `saved_query_folder` (`id`) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `semantic_column_map`
--

DROP TABLE IF EXISTS `semantic_column_map`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `semantic_column_map` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT,
  `semantic_registry_id` bigint unsigned NOT NULL,
  `workspace_id` varchar(100) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `workspace_norm` varchar(100) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci GENERATED ALWAYS AS (ifnull(`workspace_id`,_utf8mb4'__global__')) STORED,
  `model_column_id` bigint unsigned DEFAULT NULL,
  `table_name` varchar(200) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `column_name` varchar(200) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `priority_rank` int NOT NULL DEFAULT '0',
  `confidence_score` decimal(4,3) DEFAULT NULL,
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_map_semreg_workspace_modelcol` (`semantic_registry_id`,`workspace_norm`,`model_column_id`),
  UNIQUE KEY `uq_map_semreg_workspace_tablecol` (`semantic_registry_id`,`workspace_norm`,`table_name`,`column_name`),
  KEY `idx_map_workspace_modelcol` (`workspace_norm`,`model_column_id`),
  KEY `idx_map_workspace_tablecol` (`workspace_norm`,`table_name`,`column_name`),
  CONSTRAINT `fk_semantic_map_registry` FOREIGN KEY (`semantic_registry_id`) REFERENCES `semantic_registry` (`id`) ON DELETE CASCADE,
  CONSTRAINT `chk_semantic_map_confidence` CHECK (((`confidence_score` is null) or ((`confidence_score` >= 0.000) and (`confidence_score` <= 1.000))))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `semantic_concept`
--

DROP TABLE IF EXISTS `semantic_concept`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `semantic_concept` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT,
  `vertical_norm` varchar(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'generic',
  `concept_key` varchar(150) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `name` varchar(200) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `description` text CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci,
  `semantic_type` varchar(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `sub_type` varchar(200) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `entity` varchar(100) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `granularity_rank` int NOT NULL DEFAULT '0',
  `filter_allowed` tinyint(1) NOT NULL DEFAULT '1',
  `group_by_allowed` tinyint(1) NOT NULL DEFAULT '1',
  `aggregation_allowed` tinyint(1) NOT NULL DEFAULT '0',
  `is_identifier` tinyint(1) NOT NULL DEFAULT '0',
  `is_metric` tinyint(1) NOT NULL DEFAULT '0',
  `display_priority` int NOT NULL DEFAULT '0',
  `sensitive` tinyint(1) NOT NULL DEFAULT '0',
  `status` varchar(20) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'active',
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_concept_vertical_key` (`vertical_norm`,`concept_key`),
  KEY `idx_concept_vertical_type` (`vertical_norm`,`semantic_type`),
  KEY `idx_concept_key` (`concept_key`)
) ENGINE=InnoDB AUTO_INCREMENT=25297 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `semantic_concept_alias`
--

DROP TABLE IF EXISTS `semantic_concept_alias`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `semantic_concept_alias` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT,
  `vertical_norm` varchar(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'generic',
  `alias_key` varchar(200) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `concept_key` varchar(150) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `match_kind` varchar(20) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'exact',
  `weight` decimal(4,3) NOT NULL DEFAULT '1.000',
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_alias` (`vertical_norm`,`alias_key`,`match_kind`),
  KEY `idx_alias_vertical` (`vertical_norm`),
  KEY `idx_alias_concept` (`vertical_norm`,`concept_key`)
) ENGINE=InnoDB AUTO_INCREMENT=205 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `semantic_registry`
--

DROP TABLE IF EXISTS `semantic_registry`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `semantic_registry` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT,
  `vertical` varchar(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `vertical_norm` varchar(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci GENERATED ALWAYS AS (ifnull(`vertical`,_utf8mb4'__global__')) STORED,
  `concept_key` varchar(150) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `semantic_type` varchar(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `sub_type` varchar(200) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `entity` varchar(100) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `description` text CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci,
  `granularity_rank` int NOT NULL DEFAULT '0',
  `filter_allowed` tinyint(1) NOT NULL DEFAULT '1',
  `group_by_allowed` tinyint(1) NOT NULL DEFAULT '1',
  `aggregation_allowed` tinyint(1) NOT NULL DEFAULT '1',
  `is_identifier` tinyint(1) NOT NULL DEFAULT '0',
  `is_metric` tinyint(1) NOT NULL DEFAULT '0',
  `display_priority` int NOT NULL DEFAULT '0',
  `sensitive` tinyint(1) NOT NULL DEFAULT '0',
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_semantic_registry_vertical_concept` (`vertical_norm`,`concept_key`),
  KEY `idx_semantic_registry_vertical_type` (`vertical_norm`,`semantic_type`),
  KEY `idx_semantic_registry_vertical_entity` (`vertical_norm`,`entity`)
) ENGINE=InnoDB AUTO_INCREMENT=82 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `semantic_relationship`
--

DROP TABLE IF EXISTS `semantic_relationship`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `semantic_relationship` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT,
  `parent_concept_id` bigint unsigned NOT NULL,
  `child_concept_id` bigint unsigned NOT NULL,
  `relationship_type` varchar(100) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_rel` (`parent_concept_id`,`child_concept_id`,`relationship_type`),
  KEY `idx_rel_parent` (`parent_concept_id`),
  KEY `idx_rel_child` (`child_concept_id`),
  CONSTRAINT `fk_semantic_rel_child` FOREIGN KEY (`child_concept_id`) REFERENCES `semantic_registry` (`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_semantic_rel_parent` FOREIGN KEY (`parent_concept_id`) REFERENCES `semantic_registry` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB AUTO_INCREMENT=181 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `semantic_suggestion_item`
--

DROP TABLE IF EXISTS `semantic_suggestion_item`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `semantic_suggestion_item` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT,
  `run_id` bigint unsigned NOT NULL,
  `model_column_id` bigint unsigned NOT NULL,
  `model_table_id` bigint unsigned DEFAULT NULL,
  `table_name` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `column_name` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `data_type` varchar(100) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `description` text CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci,
  `samples_json` json DEFAULT NULL,
  `signals_json` json DEFAULT NULL,
  `llm_raw_json` json DEFAULT NULL,
  `proposed_concept_key` varchar(150) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `proposed_concept_id` bigint unsigned DEFAULT NULL,
  `proposed_concept_source` varchar(30) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'llm',
  `proposed_fallback_concept` tinyint(1) NOT NULL DEFAULT '0',
  `proposed_concept_key_raw` varchar(200) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `proposed_semantic_type` varchar(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `proposed_sub_type` varchar(200) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `proposed_entity` varchar(100) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `proposed_granularity_rank` int NOT NULL DEFAULT '0',
  `proposed_filter_allowed` tinyint(1) NOT NULL DEFAULT '1',
  `proposed_group_by_allowed` tinyint(1) NOT NULL DEFAULT '1',
  `proposed_aggregation_allowed` tinyint(1) NOT NULL DEFAULT '1',
  `proposed_is_identifier` tinyint(1) NOT NULL DEFAULT '0',
  `proposed_is_metric` tinyint(1) NOT NULL DEFAULT '0',
  `proposed_display_priority` int NOT NULL DEFAULT '0',
  `proposed_sensitive` tinyint(1) NOT NULL DEFAULT '0',
  `confidence` decimal(5,4) DEFAULT NULL,
  `reasons_json` json DEFAULT NULL,
  `warnings_json` json DEFAULT NULL,
  `validation_errors_json` json DEFAULT NULL,
  `is_valid` tinyint(1) NOT NULL DEFAULT '0',
  `decision_status` varchar(32) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'pending',
  `decision_reason` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `applied_at` datetime DEFAULT NULL,
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_sem_suggestion_item_run_column` (`run_id`,`model_column_id`),
  KEY `idx_sem_suggestion_item_run` (`run_id`),
  KEY `idx_sem_suggestion_item_status` (`decision_status`),
  KEY `idx_sem_suggestion_item_type` (`proposed_semantic_type`),
  KEY `idx_sem_suggestion_item_conf` (`confidence`),
  KEY `idx_item_concept` (`proposed_concept_id`),
  KEY `idx_item_concept_source` (`proposed_concept_source`),
  CONSTRAINT `fk_sem_suggestion_item_run` FOREIGN KEY (`run_id`) REFERENCES `semantic_suggestion_run` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `semantic_suggestion_run`
--

DROP TABLE IF EXISTS `semantic_suggestion_run`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `semantic_suggestion_run` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT,
  `workspace_id` varchar(100) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `vertical` varchar(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `vertical_norm` varchar(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci GENERATED ALWAYS AS (ifnull(`vertical`,_utf8mb4'__global__')) STORED,
  `status` varchar(32) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'created',
  `params_json` json DEFAULT NULL,
  `total_columns` int NOT NULL DEFAULT '0',
  `processed_columns` int NOT NULL DEFAULT '0',
  `valid_items` int NOT NULL DEFAULT '0',
  `invalid_items` int NOT NULL DEFAULT '0',
  `auto_approved_items` int NOT NULL DEFAULT '0',
  `approved_items` int NOT NULL DEFAULT '0',
  `rejected_items` int NOT NULL DEFAULT '0',
  `applied_items` int NOT NULL DEFAULT '0',
  `failed_apply_items` int NOT NULL DEFAULT '0',
  `error_message` text CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci,
  `started_at` datetime DEFAULT NULL,
  `completed_at` datetime DEFAULT NULL,
  `created_by` varchar(128) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_sem_suggestion_run_vertical` (`vertical_norm`),
  KEY `idx_sem_suggestion_run_status` (`status`),
  KEY `idx_sem_suggestion_run_workspace_status` (`workspace_id`,`status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `semantic_value_alias`
--

DROP TABLE IF EXISTS `semantic_value_alias`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `semantic_value_alias` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT,
  `vertical_norm` varchar(50) NOT NULL DEFAULT 'generic',
  `semantic_concept_id` bigint unsigned NOT NULL,
  `canonical_value` varchar(300) NOT NULL,
  `alias_value` varchar(300) NOT NULL,
  `match_kind` varchar(20) NOT NULL DEFAULT 'contains',
  `weight` decimal(4,3) NOT NULL DEFAULT '1.000',
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_val_alias` (`vertical_norm`,`semantic_concept_id`,`alias_value`,`match_kind`),
  KEY `idx_val_alias_concept` (`vertical_norm`,`semantic_concept_id`),
  KEY `fk_val_alias_concept` (`semantic_concept_id`),
  CONSTRAINT `fk_val_alias_concept` FOREIGN KEY (`semantic_concept_id`) REFERENCES `semantic_concept` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB AUTO_INCREMENT=138 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `skill_executions`
--

DROP TABLE IF EXISTS `skill_executions`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `skill_executions` (
  `id` char(36) NOT NULL,
  `skill_id` char(36) NOT NULL,
  `workspace_id` varchar(128) NOT NULL,
  `schedule_id` char(36) DEFAULT NULL,
  `job_id` varchar(36) DEFAULT NULL,
  `status` varchar(32) NOT NULL DEFAULT 'queued',
  `triggered_by` varchar(255) DEFAULT NULL,
  `started_at` datetime DEFAULT NULL,
  `completed_at` datetime DEFAULT NULL,
  `error_message` text,
  `result_json` json DEFAULT NULL,
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_skill_executions_skill_id_status` (`skill_id`,`status`),
  KEY `idx_skill_executions_job_id` (`job_id`),
  KEY `fk_skill_executions_schedule` (`schedule_id`),
  CONSTRAINT `fk_skill_executions_schedule` FOREIGN KEY (`schedule_id`) REFERENCES `skill_schedules` (`id`) ON DELETE SET NULL ON UPDATE CASCADE,
  CONSTRAINT `fk_skill_executions_skill` FOREIGN KEY (`skill_id`) REFERENCES `query_skills` (`id`) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `skill_schedules`
--

DROP TABLE IF EXISTS `skill_schedules`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `skill_schedules` (
  `id` char(36) NOT NULL,
  `skill_id` char(36) NOT NULL,
  `workspace_id` varchar(128) NOT NULL,
  `cron_expr` varchar(128) NOT NULL,
  `timezone` varchar(64) NOT NULL DEFAULT 'UTC',
  `next_run_at` datetime DEFAULT NULL,
  `last_run_at` datetime DEFAULT NULL,
  `is_active` tinyint NOT NULL DEFAULT '1',
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` timestamp NULL DEFAULT NULL ON UPDATE CURRENT_TIMESTAMP,
  `catch_up` tinyint(1) NOT NULL DEFAULT '0' COMMENT 'If 0, missed runs are skipped after Beat downtime. If 1, all missed runs fire on recovery.',
  PRIMARY KEY (`id`),
  KEY `idx_skill_schedules_skill_id` (`skill_id`),
  KEY `idx_skill_schedules_next_run` (`next_run_at`,`is_active`),
  CONSTRAINT `fk_skill_schedules_skill` FOREIGN KEY (`skill_id`) REFERENCES `query_skills` (`id`) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `user_domain_mapping`
--

DROP TABLE IF EXISTS `user_domain_mapping`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `user_domain_mapping` (
  `user_id` varchar(255) NOT NULL,
  `domain_id` bigint unsigned NOT NULL,
  `can_read` tinyint(1) NOT NULL DEFAULT '1',
  `can_edit` tinyint(1) NOT NULL DEFAULT '0',
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`user_id`,`domain_id`),
  KEY `ix_udm_domain` (`domain_id`),
  KEY `ix_udm_user` (`user_id`),
  CONSTRAINT `fk_udm_domain` FOREIGN KEY (`domain_id`) REFERENCES `domain` (`id`) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `user_product_map`
--

DROP TABLE IF EXISTS `user_product_map`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `user_product_map` (
  `user_product_map_id` int NOT NULL AUTO_INCREMENT,
  `product_id` varchar(45) NOT NULL,
  `user_id` varchar(45) NOT NULL,
  PRIMARY KEY (`user_product_map_id`),
  UNIQUE KEY `user_product_map_id_UNIQUE` (`user_product_map_id`),
  KEY `fk_product_idx` (`product_id`),
  KEY `fk_user_idx` (`user_id`),
  CONSTRAINT `fk_user_product_map_product` FOREIGN KEY (`product_id`) REFERENCES `products` (`product_id`) ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT `fk_user_product_map_user` FOREIGN KEY (`user_id`) REFERENCES `users` (`user_id`) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB AUTO_INCREMENT=226 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `user_roles`
--

DROP TABLE IF EXISTS `user_roles`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `user_roles` (
  `id` int NOT NULL AUTO_INCREMENT,
  `user_id` varchar(255) NOT NULL,
  `role_id` int NOT NULL,
  `granted_by` varchar(255) DEFAULT NULL COMMENT 'user_id of admin who assigned this role',
  `granted_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_user_role` (`user_id`,`role_id`),
  KEY `ix_user_roles_user_id` (`user_id`),
  KEY `ix_user_roles_role_id` (`role_id`),
  CONSTRAINT `fk_user_roles_role` FOREIGN KEY (`role_id`) REFERENCES `roles` (`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_user_roles_user` FOREIGN KEY (`user_id`) REFERENCES `users` (`user_id`) ON DELETE CASCADE
) ENGINE=InnoDB AUTO_INCREMENT=2 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `users`
--

DROP TABLE IF EXISTS `users`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
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
  `otp_totp_secret` varchar(128) DEFAULT NULL,
  `otp_totp_enabled` tinyint(1) NOT NULL DEFAULT '0',
  `otp_totp_confirmed_at` datetime DEFAULT NULL,
  `otp_mfa_method` varchar(20) DEFAULT NULL,
  `last_log_in` datetime DEFAULT NULL,
  `two_factor_preference` varchar(45) NOT NULL DEFAULT 'Email',
  PRIMARY KEY (`user_id`),
  UNIQUE KEY `email_UNIQUE` (`email`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `workspace`
--

DROP TABLE IF EXISTS `workspace`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `workspace` (
  `id` varchar(128) NOT NULL,
  `display_name` varchar(255) DEFAULT NULL,
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `organization_id` varchar(128) DEFAULT NULL,
  `datasource_id` bigint unsigned DEFAULT NULL,
  `name` varchar(255) DEFAULT NULL,
  `description` text,
  `is_active` tinyint(1) NOT NULL DEFAULT '1',
  `default_catalog` varchar(255) DEFAULT NULL,
  `default_schema` varchar(255) DEFAULT NULL,
  `updated_at` timestamp NULL DEFAULT NULL ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `ix_workspace_org` (`organization_id`),
  KEY `ix_workspace_datasource` (`datasource_id`),
  KEY `ix_workspace_org_active` (`organization_id`,`is_active`),
  CONSTRAINT `fk_workspace_datasource` FOREIGN KEY (`datasource_id`) REFERENCES `datasource` (`id`) ON DELETE RESTRICT ON UPDATE CASCADE,
  CONSTRAINT `fk_workspace_org` FOREIGN KEY (`organization_id`) REFERENCES `organization` (`id`) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `workspace_column`
--

DROP TABLE IF EXISTS `workspace_column`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `workspace_column` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT,
  `workspace_table_id` bigint unsigned NOT NULL,
  `column_name` varchar(255) NOT NULL,
  `data_type` varchar(255) NOT NULL,
  `nullable` tinyint(1) NOT NULL DEFAULT '1',
  `ordinal_position` int NOT NULL DEFAULT '0',
  `exists_in_dbx` tinyint(1) NOT NULL DEFAULT '1',
  `last_seen_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` timestamp NULL DEFAULT NULL ON UPDATE CURRENT_TIMESTAMP,
  `description` text,
  `is_active` tinyint(1) NOT NULL DEFAULT '1',
  `origin` varchar(32) DEFAULT NULL,
  `is_missing_in_source` tinyint(1) NOT NULL DEFAULT '0',
  `semantic_type` varchar(100) DEFAULT NULL,
  `semantic_entity` varchar(100) DEFAULT NULL,
  `semantic_sub_type` varchar(200) DEFAULT NULL,
  `semantic_source` varchar(20) DEFAULT NULL,
  `semantic_confidence` decimal(6,5) DEFAULT NULL,
  `semantic_concept_key` varchar(128) DEFAULT NULL,
  `semantic_concept_id` bigint unsigned DEFAULT NULL,
  `semantic_assigned_at` datetime DEFAULT NULL,
  `semantic_reasons_json` json DEFAULT NULL,
  `sample_values_json` json DEFAULT NULL,
  `sample_stats_json` json DEFAULT NULL,
  `sample_ran_at` datetime DEFAULT NULL,
  `sample_error` text,
  `metadata_updated_at` datetime DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_wscol` (`workspace_table_id`,`column_name`),
  KEY `ix_wscol_name` (`column_name`),
  CONSTRAINT `fk_wscol_table` FOREIGN KEY (`workspace_table_id`) REFERENCES `workspace_table` (`id`) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB AUTO_INCREMENT=14307 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `workspace_destinations`
--

DROP TABLE IF EXISTS `workspace_destinations`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `workspace_destinations` (
  `id` int NOT NULL AUTO_INCREMENT,
  `workspace_id` varchar(128) COLLATE utf8mb4_unicode_ci NOT NULL,
  `name` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `description` varchar(500) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `destination_type` enum('slack','teams','webhook','email_group') COLLATE utf8mb4_unicode_ci NOT NULL,
  `config_json_encrypted` text COLLATE utf8mb4_unicode_ci NOT NULL,
  `is_active` tinyint(1) NOT NULL DEFAULT '1',
  `last_tested_at` datetime DEFAULT NULL,
  `last_test_status` enum('success','failed') COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `last_test_message` text COLLATE utf8mb4_unicode_ci,
  `last_used_at` datetime DEFAULT NULL,
  `usage_count` int NOT NULL DEFAULT '0',
  `created_by` int DEFAULT NULL,
  `updated_by` int DEFAULT NULL,
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `ix_workspace_destinations_workspace` (`workspace_id`,`is_active`),
  KEY `ix_workspace_destinations_type` (`workspace_id`,`destination_type`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `workspace_features`
--

DROP TABLE IF EXISTS `workspace_features`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `workspace_features` (
  `id` int NOT NULL AUTO_INCREMENT,
  `workspace_id` varchar(128) NOT NULL,
  `feature_key` varchar(64) NOT NULL,
  `is_active` tinyint(1) NOT NULL DEFAULT '1',
  `granted_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `granted_by` varchar(255) DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_workspace_feature` (`workspace_id`,`feature_key`),
  KEY `ix_workspace_features_workspace` (`workspace_id`,`is_active`),
  CONSTRAINT `fk_workspace_features_workspace` FOREIGN KEY (`workspace_id`) REFERENCES `workspace` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `workspace_llm`
--

DROP TABLE IF EXISTS `workspace_llm`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `workspace_llm` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT,
  `workspace_id` varchar(255) NOT NULL,
  `name` varchar(255) NOT NULL,
  `provider` varchar(64) NOT NULL,
  `model_name` varchar(255) NOT NULL,
  `role` varchar(64) NOT NULL,
  `api_key_encrypted` text,
  `endpoint_url` varchar(500) DEFAULT NULL,
  `is_active` tinyint(1) NOT NULL DEFAULT '1',
  `config_json` text,
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` timestamp NULL DEFAULT NULL ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `ix_workspace_llm_workspace` (`workspace_id`),
  KEY `ix_workspace_llm_workspace_role` (`workspace_id`,`role`),
  KEY `ix_workspace_llm_active` (`workspace_id`,`is_active`)
) ENGINE=InnoDB AUTO_INCREMENT=2 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `workspace_membership`
--

DROP TABLE IF EXISTS `workspace_membership`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `workspace_membership` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT,
  `workspace_id` varchar(128) NOT NULL,
  `user_id` varchar(255) NOT NULL,
  `role` varchar(64) NOT NULL DEFAULT 'member',
  `is_active` tinyint(1) NOT NULL DEFAULT '1',
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` timestamp NULL DEFAULT NULL ON UPDATE CURRENT_TIMESTAMP,
  `is_default` tinyint(1) NOT NULL DEFAULT '0',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_workspace_membership` (`workspace_id`,`user_id`),
  KEY `ix_workspace_membership_user` (`user_id`),
  KEY `ix_workspace_membership_workspace_role` (`workspace_id`,`role`),
  KEY `ix_workspace_membership_user_default` (`user_id`,`is_default`),
  CONSTRAINT `fk_workspace_membership_user` FOREIGN KEY (`user_id`) REFERENCES `users` (`user_id`) ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT `fk_workspace_membership_workspace` FOREIGN KEY (`workspace_id`) REFERENCES `workspace` (`id`) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `workspace_table`
--

DROP TABLE IF EXISTS `workspace_table`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `workspace_table` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT,
  `workspace_id` varchar(128) NOT NULL,
  `model_table_id` bigint unsigned DEFAULT NULL,
  `catalog_name` varchar(255) NOT NULL,
  `schema_name` varchar(255) NOT NULL DEFAULT 'asset',
  `table_name` varchar(255) NOT NULL,
  `full_name` varchar(600) NOT NULL,
  `variant_code` varchar(255) DEFAULT NULL,
  `is_qe` tinyint(1) NOT NULL DEFAULT '0',
  `exists_in_dbx` tinyint(1) NOT NULL DEFAULT '1',
  `last_seen_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` timestamp NULL DEFAULT NULL ON UPDATE CURRENT_TIMESTAMP,
  `source_table_name` varchar(255) DEFAULT NULL,
  `description` text,
  `origin` varchar(32) DEFAULT NULL,
  `is_missing_in_source` tinyint(1) NOT NULL DEFAULT '0',
  `metadata_synced_at` datetime DEFAULT NULL,
  `metadata_updated_at` datetime DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_ws_full` (`workspace_id`,`full_name`),
  KEY `ix_ws_model` (`workspace_id`,`model_table_id`),
  KEY `ix_ws_variant` (`workspace_id`,`variant_code`),
  KEY `ix_ws_unmapped` (`workspace_id`,`schema_name`,`model_table_id`,`table_name`),
  KEY `fk_ws_table_model` (`model_table_id`),
  CONSTRAINT `fk_ws_table_model` FOREIGN KEY (`model_table_id`) REFERENCES `model_table` (`id`) ON DELETE RESTRICT ON UPDATE CASCADE,
  CONSTRAINT `fk_ws_table_ws` FOREIGN KEY (`workspace_id`) REFERENCES `workspace` (`id`) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB AUTO_INCREMENT=533 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `zip_code`
--

DROP TABLE IF EXISTS `zip_code`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `zip_code` (
  `zip` char(5) NOT NULL,
  `state_id` char(2) NOT NULL,
  PRIMARY KEY (`zip`),
  KEY `ix_zip_state` (`state_id`),
  KEY `idx_state` (`state_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping events for database 'query_forge_demo'
--

--
-- Dumping routines for database 'query_forge_demo'
--
/*!40103 SET TIME_ZONE=@OLD_TIME_ZONE */;

/*!40101 SET SQL_MODE=@OLD_SQL_MODE */;
/*!40014 SET FOREIGN_KEY_CHECKS=@OLD_FOREIGN_KEY_CHECKS */;
/*!40014 SET UNIQUE_CHECKS=@OLD_UNIQUE_CHECKS */;
/*!40101 SET CHARACTER_SET_CLIENT=@OLD_CHARACTER_SET_CLIENT */;
/*!40101 SET CHARACTER_SET_RESULTS=@OLD_CHARACTER_SET_RESULTS */;
/*!40101 SET COLLATION_CONNECTION=@OLD_COLLATION_CONNECTION */;
/*!40111 SET SQL_NOTES=@OLD_SQL_NOTES */;

-- Dump completed on 2026-03-18 18:16:03
