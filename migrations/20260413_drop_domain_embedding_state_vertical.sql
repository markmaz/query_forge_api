ALTER TABLE domain_embedding_state
  DROP INDEX idx_domain_embedding_state_vertical,
  DROP COLUMN vertical_norm;
