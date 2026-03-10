ALTER TABLE ingestion_run
  ADD COLUMN IF NOT EXISTS columns_total INT NOT NULL DEFAULT 0 AFTER tables_updated,
  ADD COLUMN IF NOT EXISTS columns_done INT NOT NULL DEFAULT 0 AFTER columns_total,
  ADD COLUMN IF NOT EXISTS columns_failed INT NOT NULL DEFAULT 0 AFTER columns_done,
  ADD COLUMN IF NOT EXISTS current_phase VARCHAR(50) NULL AFTER columns_updated,
  ADD COLUMN IF NOT EXISTS current_table VARCHAR(255) NULL AFTER current_phase,
  ADD COLUMN IF NOT EXISTS current_column VARCHAR(255) NULL AFTER current_table;
