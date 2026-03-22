-- Add missing semantic_updated_at to workspace_column.
-- Earlier metadata expansion added the semantic fields but missed this timestamp,
-- while enrichment and semantic assignment already write to it.

SET @db_name := DATABASE();

DELIMITER $$

DROP PROCEDURE IF EXISTS qf_add_column_if_missing $$
CREATE PROCEDURE qf_add_column_if_missing(
  IN p_table_name VARCHAR(128),
  IN p_column_name VARCHAR(128),
  IN p_column_def TEXT
)
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = DATABASE()
      AND table_name = p_table_name
      AND column_name = p_column_name
  ) THEN
    SET @sql := CONCAT('ALTER TABLE `', p_table_name, '` ADD COLUMN ', p_column_def);
    PREPARE stmt FROM @sql;
    EXECUTE stmt;
    DEALLOCATE PREPARE stmt;
  END IF;
END $$

DELIMITER ;

CALL qf_add_column_if_missing(
  'workspace_column',
  'semantic_updated_at',
  '`semantic_updated_at` DATETIME NULL AFTER `semantic_assigned_at`'
);

DROP PROCEDURE IF EXISTS qf_add_column_if_missing;
