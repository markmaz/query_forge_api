ALTER TABLE semantic_suggestion_run
  DROP INDEX idx_sem_suggestion_run_vertical,
  DROP COLUMN vertical_norm,
  DROP COLUMN vertical;
