ALTER TABLE semantic_update_candidate
  ADD COLUMN governance_reason_code VARCHAR(64) NULL AFTER auto_apply_eligible,
  ADD COLUMN review_notes TEXT NULL AFTER governance_reason_code;
