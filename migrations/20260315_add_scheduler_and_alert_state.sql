-- Migration: 20260315_add_scheduler_and_alert_state.sql
--
-- Adds:
--   skill_schedules.catch_up         — whether to replay missed runs after downtime
--   query_skills.last_alert_state    — tracks last threshold evaluation for on_change mode
--   query_skills.alert_acknowledged_at — for manual acknowledgement of alerts
--
-- Run against the application database before deploying skills v2.

ALTER TABLE skill_schedules
    ADD COLUMN catch_up TINYINT(1) NOT NULL DEFAULT 0
        COMMENT 'If 0, missed runs are skipped after Beat downtime. If 1, all missed runs fire on recovery.';

ALTER TABLE query_skills
    ADD COLUMN last_alert_state JSON NULL
        COMMENT 'Stores last evaluated condition results for threshold_alert on_change mode.',
    ADD COLUMN alert_acknowledged_at DATETIME NULL
        COMMENT 'Set when a user manually acknowledges an alert. Cleared on next state change.';

-- Index to support efficient alert state lookups
CREATE INDEX ix_query_skills_alert_state
    ON query_skills (id, last_alert_state(32));
