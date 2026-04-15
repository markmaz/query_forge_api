ALTER TABLE planner_rerank_policy_candidate
  DROP INDEX idx_prpc_scope,
  DROP COLUMN vertical_norm,
  ADD INDEX idx_prpc_scope (workspace_id);
