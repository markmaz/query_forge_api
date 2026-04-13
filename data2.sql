-- MySQL dump 10.13  Distrib 9.5.0, for macos15.7 (arm64)
--
-- Host: localhost    Database: query_forge_rbac
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
SET @MYSQLDUMP_TEMP_LOG_BIN = @@SESSION.SQL_LOG_BIN;
SET @@SESSION.SQL_LOG_BIN= 0;

--
-- GTID state at the beginning of the backup 
--

SET @@GLOBAL.GTID_PURGED=/*!80000 '+'*/ 'b68dbef8-2213-11f0-bc75-d49fa0457a92:1-66449';

--
-- Dumping data for table `planner_rerank_policy`
--

LOCK TABLES `planner_rerank_policy` WRITE;
/*!40000 ALTER TABLE `planner_rerank_policy` DISABLE KEYS */;
INSERT INTO `planner_rerank_policy` VALUES (1,'student_listing_school_literal','Student listing school literal','When a user prompts with a proper school name invoke this policy','workspace_domain','ws_3de8526699214b2d87830352',NULL,9,100,1,0,'{\"boost\": 0.2, \"penalty\": 0.3, \"version\": 1, \"max_effect\": 0.3, \"penalize_missing\": [\"SCHOOL_NAME\"], \"when_signals_all\": [\"student_listing\", \"school_literal_present\"], \"when_signals_any\": [], \"require_for_bonus\": [\"STUDENT_IDENTITY\"], \"exclude_signals_any\": [], \"prefer_capabilities\": [\"SCHOOL_NAME\", \"STUDENT_IDENTITY\"]}','2026-03-25 19:08:11','2026-03-25 19:28:14'),(2,'calendar_days_off_school_literal','Calendar Days Off By School',NULL,'workspace_domain','ws_3de8526699214b2d87830352',NULL,6,120,1,0,'{\"boost\": 0.22, \"penalty\": 0.28, \"version\": 1, \"max_effect\": 0.3, \"penalize_missing\": [\"CALENDAR_DATE\", \"SCHOOL_NAME\"], \"when_signals_all\": [\"calendar_days_off_prompt\", \"school_literal_present\", \"time_constraint_present\"], \"when_signals_any\": [], \"require_for_bonus\": [\"CALENDAR_DATE\"], \"exclude_signals_any\": [], \"prefer_capabilities\": [\"CALENDAR_DATE\", \"SCHOOL_NAME\", \"SCHOOL_DAY_FLAG\", \"NON_INSTRUCTIONAL_DAY\"]}','2026-03-25 20:53:34','2026-03-25 20:53:34'),(3,'calendar_days_off_core','Calendar Days Off Core',NULL,'workspace_domain','ws_3de8526699214b2d87830352',NULL,6,100,1,0,'{\"boost\": 0.16, \"penalty\": 0.2, \"version\": 1, \"max_effect\": 0.22, \"penalize_missing\": [\"CALENDAR_DATE\"], \"when_signals_all\": [\"calendar_days_off_prompt\"], \"when_signals_any\": [], \"require_for_bonus\": [\"CALENDAR_DATE\"], \"exclude_signals_any\": [], \"prefer_capabilities\": [\"CALENDAR_DATE\", \"SCHOOL_DAY_FLAG\", \"NON_INSTRUCTIONAL_DAY\"]}','2026-03-25 20:56:31','2026-03-25 20:56:31'),(4,'student_age_extreme','Student Age',NULL,'workspace_domain','ws_3de8526699214b2d87830352',NULL,14,120,1,0,'{\"boost\": 0.24, \"penalty\": 0.3, \"version\": 1, \"max_effect\": 0.3, \"penalize_missing\": [\"BIRTH_DATE\"], \"when_signals_all\": [\"student_listing\", \"age_extreme_prompt\"], \"when_signals_any\": [], \"require_for_bonus\": [\"STUDENT_IDENTITY\"], \"exclude_signals_any\": [], \"prefer_capabilities\": [\"STUDENT_IDENTITY\", \"BIRTH_DATE\"]}','2026-03-25 23:20:03','2026-03-25 23:20:40');
/*!40000 ALTER TABLE `planner_rerank_policy` ENABLE KEYS */;
UNLOCK TABLES;
SET @@SESSION.SQL_LOG_BIN = @MYSQLDUMP_TEMP_LOG_BIN;
/*!40103 SET TIME_ZONE=@OLD_TIME_ZONE */;

/*!40101 SET SQL_MODE=@OLD_SQL_MODE */;
/*!40014 SET FOREIGN_KEY_CHECKS=@OLD_FOREIGN_KEY_CHECKS */;
/*!40014 SET UNIQUE_CHECKS=@OLD_UNIQUE_CHECKS */;
/*!40101 SET CHARACTER_SET_CLIENT=@OLD_CHARACTER_SET_CLIENT */;
/*!40101 SET CHARACTER_SET_RESULTS=@OLD_CHARACTER_SET_RESULTS */;
/*!40101 SET COLLATION_CONNECTION=@OLD_COLLATION_CONNECTION */;
/*!40111 SET SQL_NOTES=@OLD_SQL_NOTES */;

-- Dump completed on 2026-04-07 19:59:51
