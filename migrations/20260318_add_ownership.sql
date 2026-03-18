-- Migration: 20260318_add_ownership.sql
--
-- Adds created_by and is_shared to saved_query and query_skills.
-- Backfills NULL created_by with a system user for legacy data.
--
-- Seam adaptations:
--   users.user_id    — VARCHAR(255) PK (not id INT)
--   users.status     — '0' inactive (not is_active)
--   users.password   — column name (not password_hash)
--   saved_query.owner_user_id already exists — backfill created_by from it
--   query_skills.created_by already exists (VARCHAR 255) — skip ADD COLUMN

-- ---------------------------------------------------------------------------
-- Step 1: Create system user (if not exists)
-- Used to own legacy data with no creator.
-- ---------------------------------------------------------------------------

INSERT INTO users (user_id, username, password, email, status)
SELECT
    'system',
    'system',
    'SYSTEM_USER_NO_LOGIN',
    'system@queryforge.internal',
    '0'           -- inactive — cannot log in
WHERE NOT EXISTS (
    SELECT 1 FROM users WHERE email = 'system@queryforge.internal'
);

-- ---------------------------------------------------------------------------
-- Step 2: Add created_by to saved_query (does not exist)
-- Backfill from owner_user_id where available, else system user
-- ---------------------------------------------------------------------------

ALTER TABLE saved_query
    ADD COLUMN created_by VARCHAR(255) NULL
        COMMENT 'User who created this query. NULL = legacy, migrated to system user.';

-- Backfill from owner_user_id (existing ownership column)
UPDATE saved_query
SET created_by = owner_user_id
WHERE created_by IS NULL AND owner_user_id IS NOT NULL;

-- Remaining NULLs → system user
UPDATE saved_query
SET created_by = (
    SELECT user_id FROM users WHERE email = 'system@queryforge.internal' LIMIT 1
)
WHERE created_by IS NULL;

-- FK constraint after backfill
ALTER TABLE saved_query
    ADD CONSTRAINT fk_saved_query_created_by
        FOREIGN KEY (created_by) REFERENCES users(user_id) ON DELETE SET NULL;

CREATE INDEX ix_saved_query_created_by
    ON saved_query (created_by, workspace_id);

-- ---------------------------------------------------------------------------
-- Step 3: query_skills.created_by already exists — just backfill NULLs
-- ---------------------------------------------------------------------------

UPDATE query_skills
SET created_by = (
    SELECT user_id FROM users WHERE email = 'system@queryforge.internal' LIMIT 1
)
WHERE created_by IS NULL;

-- ---------------------------------------------------------------------------
-- Step 4: Add is_shared to both tables
-- ---------------------------------------------------------------------------

ALTER TABLE saved_query
    ADD COLUMN is_shared TINYINT(1) NOT NULL DEFAULT 0
        COMMENT '1 = any workspace member with query_studio:user can read this query';

ALTER TABLE query_skills
    ADD COLUMN is_shared TINYINT(1) NOT NULL DEFAULT 0
        COMMENT '1 = any workspace member with skills:user can read this skill';

CREATE INDEX ix_saved_query_shared
    ON saved_query (workspace_id, is_shared);

CREATE INDEX ix_query_skills_shared
    ON query_skills (workspace_id, is_shared);

-- ---------------------------------------------------------------------------
-- Step 5: Verify
-- ---------------------------------------------------------------------------

-- SELECT COUNT(*) FROM saved_query WHERE created_by IS NULL;   -- Expected: 0
-- SELECT COUNT(*) FROM query_skills WHERE created_by IS NULL;  -- Expected: 0
-- DESCRIBE saved_query;   -- is_shared present, created_by present
-- DESCRIBE query_skills;  -- is_shared present
