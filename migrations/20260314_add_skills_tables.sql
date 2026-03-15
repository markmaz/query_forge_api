CREATE TABLE IF NOT EXISTS query_skills (
  id char(36) NOT NULL,
  workspace_id varchar(128) NOT NULL,
  name varchar(255) NOT NULL,
  skill_type varchar(64) NOT NULL,
  query_id char(36) DEFAULT NULL,
  config_json json DEFAULT NULL,
  is_active tinyint NOT NULL DEFAULT 1,
  created_by varchar(255) NOT NULL,
  created_at timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at timestamp NULL DEFAULT NULL ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_query_skills_workspace_active (workspace_id, is_active),
  KEY idx_query_skills_skill_type (skill_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS skill_schedules (
  id char(36) NOT NULL,
  skill_id char(36) NOT NULL,
  workspace_id varchar(128) NOT NULL,
  cron_expr varchar(128) NOT NULL,
  timezone varchar(64) NOT NULL DEFAULT 'UTC',
  next_run_at datetime DEFAULT NULL,
  last_run_at datetime DEFAULT NULL,
  is_active tinyint NOT NULL DEFAULT 1,
  created_at timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at timestamp NULL DEFAULT NULL ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_skill_schedules_skill_id (skill_id),
  KEY idx_skill_schedules_next_run (next_run_at, is_active),
  CONSTRAINT fk_skill_schedules_skill
    FOREIGN KEY (skill_id) REFERENCES query_skills (id)
    ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS skill_executions (
  id char(36) NOT NULL,
  skill_id char(36) NOT NULL,
  workspace_id varchar(128) NOT NULL,
  schedule_id char(36) DEFAULT NULL,
  job_id varchar(36) DEFAULT NULL,
  status varchar(32) NOT NULL DEFAULT 'queued',
  triggered_by varchar(255) DEFAULT NULL,
  started_at datetime DEFAULT NULL,
  completed_at datetime DEFAULT NULL,
  error_message text,
  result_json json DEFAULT NULL,
  created_at timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_skill_executions_skill_id_status (skill_id, status),
  KEY idx_skill_executions_job_id (job_id),
  CONSTRAINT fk_skill_executions_skill
    FOREIGN KEY (skill_id) REFERENCES query_skills (id)
    ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT fk_skill_executions_schedule
    FOREIGN KEY (schedule_id) REFERENCES skill_schedules (id)
    ON DELETE SET NULL ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
