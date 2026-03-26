ALTER TABLE `domain_time_policy`
  ADD COLUMN `school_year_start_month` tinyint unsigned DEFAULT NULL AFTER `fiscal_year_start_month`,
  ADD COLUMN `school_year_end_month` tinyint unsigned DEFAULT NULL AFTER `school_year_start_month`;
