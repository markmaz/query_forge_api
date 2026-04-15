ALTER TABLE planner_cache
  DROP INDEX idx_planner_cache_lookup,
  DROP COLUMN vertical,
  ADD KEY idx_planner_cache_lookup (workspace_id, registry_version, expires_at);
