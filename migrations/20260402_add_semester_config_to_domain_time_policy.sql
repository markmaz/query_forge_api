ALTER TABLE `domain_time_policy`
  ADD COLUMN `semester_config` json DEFAULT NULL AFTER `relative_map`;
