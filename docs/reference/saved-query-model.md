# Reference: Saved Query Model

## Purpose

Describes the structure of saved queries and the query tree folder hierarchy.

## Status

NEEDS_VERIFICATION: The exact database schema for saved queries was not confirmed from code inspection. The following is inferred from the RBAC audit (which lists route class names) and the skills integration (which stores `query_id` on skill records). Verify actual fields from model files before relying on this reference.

## Saved Query (INFERRED_FROM_STRUCTURE)

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Query identifier |
| `workspace_id` | string | Workspace scope |
| `user_id` | string | Owner |
| `name` | string | Display name |
| `folder_id` | string/null | Parent folder (null = root) |
| `plan` | object | The SQL-JSON query plan |
| `sqljson` | object | The compiled SQL-JSON |
| `is_deleted` | bool | Soft-delete flag |
| `is_purged` | bool | Permanent delete flag |
| `created_at` | datetime | Creation timestamp |
| `updated_at` | datetime | Last updated timestamp |

## Folder (INFERRED_FROM_STRUCTURE)

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Folder identifier |
| `workspace_id` | string | Workspace scope |
| `user_id` | string | Owner |
| `name` | string | Display name |
| `parent_id` | string/null | Parent folder (null = root) |
| `is_deleted` | bool | Soft-delete flag |
| `is_purged` | bool | Permanent delete flag |

## Saved Query Share (INFERRED_FROM_STRUCTURE)

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Share record ID |
| `query_id` | string | Query being shared |
| `shared_with_user_id` | string | Recipient |
| `workspace_id` | string | Workspace scope |
| `created_at` | datetime | Share creation timestamp |

## Skill → Query reference

The `skill_runner.py` loads skills via:
```sql
SELECT id, workspace_id, name, skill_type, query_id, config_json, is_active
FROM ...
```
This confirms: skill records have a `query_id` foreign key, `skill_type`, `config_json`, and `is_active` flag.

## Behavior notes

- Deleted items go to "trash" (soft delete) and can be restored.
- Purged items are permanently removed.
- Query tree is per-workspace.
- Shares are per-query, per-user.

## Source grounding
- STATUS: INFERRED_FROM_STRUCTURE, NEEDS_VERIFICATION
- Sources:
  - `.claude/audits/backend-audit.md` (Task 6: route class names)
  - `app/tasks/skill_runner.py` (SQL query showing query_id field)
