-- U016__semantic_concepts_and_staging_extensions.sql

ALTER TABLE `semantic_suggestion_item`
  DROP KEY `idx_item_concept_source`,
  DROP KEY `idx_item_concept`,
  DROP COLUMN `proposed_concept_key_raw`,
  DROP COLUMN `proposed_fallback_concept`,
  DROP COLUMN `proposed_concept_source`,
  DROP COLUMN `proposed_concept_id`;

DROP TABLE IF EXISTS `semantic_concept_alias`;
DROP TABLE IF EXISTS `semantic_concept`;
