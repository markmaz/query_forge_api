-- Migration: 20260321_fix_workspace_destinations_actor_columns.sql
--
-- The workspace_destinations table was created with created_by/updated_by as INT,
-- but the application writes user ids as strings/UUIDs. This migration aligns the
-- table with the rest of the application ownership model.

ALTER TABLE workspace_destinations
    MODIFY COLUMN created_by VARCHAR(255) NULL,
    MODIFY COLUMN updated_by VARCHAR(255) NULL;
