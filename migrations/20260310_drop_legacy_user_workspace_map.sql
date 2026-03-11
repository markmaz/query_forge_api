-- Remove legacy workspace mapping table now that tenancy-native membership is in place.
-- Safe to run multiple times.

DELIMITER $$

DROP PROCEDURE IF EXISTS qf_drop_inbound_fks_to_table $$
CREATE PROCEDURE qf_drop_inbound_fks_to_table(IN p_referenced_table VARCHAR(128))
BEGIN
  DECLARE done INT DEFAULT 0;
  DECLARE v_table_name VARCHAR(128);
  DECLARE v_constraint_name VARCHAR(128);

  DECLARE cur CURSOR FOR
    SELECT
      kcu.table_name,
      kcu.constraint_name
    FROM information_schema.key_column_usage kcu
    JOIN information_schema.referential_constraints rc
      ON rc.constraint_schema = kcu.constraint_schema
     AND rc.table_name = kcu.table_name
     AND rc.constraint_name = kcu.constraint_name
    WHERE kcu.constraint_schema = DATABASE()
      AND kcu.referenced_table_schema = DATABASE()
      AND kcu.referenced_table_name = p_referenced_table
    GROUP BY kcu.table_name, kcu.constraint_name;

  DECLARE CONTINUE HANDLER FOR NOT FOUND SET done = 1;

  OPEN cur;
  read_loop: LOOP
    FETCH cur INTO v_table_name, v_constraint_name;
    IF done = 1 THEN
      LEAVE read_loop;
    END IF;

    SET @sql := CONCAT(
      'ALTER TABLE `', v_table_name,
      '` DROP FOREIGN KEY `', v_constraint_name, '`'
    );
    PREPARE stmt FROM @sql;
    EXECUTE stmt;
    DEALLOCATE PREPARE stmt;
  END LOOP;
  CLOSE cur;
END $$

DROP PROCEDURE IF EXISTS qf_drop_table_if_exists $$
CREATE PROCEDURE qf_drop_table_if_exists(IN p_table_name VARCHAR(128))
BEGIN
  IF EXISTS (
    SELECT 1
    FROM information_schema.tables
    WHERE table_schema = DATABASE()
      AND table_name = p_table_name
  ) THEN
    SET @sql := CONCAT('DROP TABLE `', p_table_name, '`');
    PREPARE stmt FROM @sql;
    EXECUTE stmt;
    DEALLOCATE PREPARE stmt;
  END IF;
END $$

DELIMITER ;

CALL qf_drop_inbound_fks_to_table('user_workspace_map');
CALL qf_drop_table_if_exists('user_workspace_map');

DROP PROCEDURE IF EXISTS qf_drop_inbound_fks_to_table;
DROP PROCEDURE IF EXISTS qf_drop_table_if_exists;
