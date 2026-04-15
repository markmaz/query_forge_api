# Saved Queries

## What it is

Saved queries are persisted query plans that users can name, organize into folders, share, and attach skills to. The query tree is the folder hierarchy that organizes saved queries within a workspace.

## Why it matters

Saved queries enable repeatability. Instead of re-running the planner every time, users save a plan once and execute it on demand. Skills and scheduled automation depend on saved queries as their data source.

## Who uses it

- **Analysts** — save queries for personal reuse and share with colleagues.
- **Skills users** — attach threshold alerts, AI summaries, and other skills to saved queries for automated monitoring.
- **Skills admins** — manage skill schedules and automation policies tied to saved queries.

## Key concepts

### Query Tree
A nested structure of folders and saved queries. The root is workspace-scoped.

### Folders
Folders organize saved queries. They can be nested, renamed, moved, trashed, and permanently purged. Routes (INFERRED_FROM_STRUCTURE — query_tree_routes.py referenced in RBAC audit but file not found at routes path; confirmed under `require_access("query_studio")` in backend-audit):
- Create folder: part of query tree creation
- Rename: FolderRename
- Move: FolderMove
- Delete: FolderDelete
- Trash: FolderTrash
- Restore from trash: FolderRestore
- Purge (permanent delete): FolderPurge

### Saved Query CRUD
- Create: `SavedQueryCreate`
- Get/Patch: `SavedQuery` (get + patch)
- Move to folder: `SavedQueryMove`
- Soft delete: `SavedQueryDelete`
- Restore from trash: `SavedQueryRestore`
- Permanent delete: `SavedQueryPurge`

### Sharing
Saved queries can be shared with specific users. `SavedQueryShares` handles `GET/POST/DELETE` for share records.

### Recent Queries
`RecentQueries` provides a list of recently accessed queries for the current user.

### Skills Attachment
Saved queries can have skills attached. When a skill is executed, it re-runs the saved query against the live data source and applies the skill logic (threshold check, AI summary, etc.).

## Related features

- [Skills](skills.md)
- [Query Studio user guide](../user-guides/query-studio.md)
- [Save and Share Query playbook](../task-playbooks/save-and-share-query.md)
- [Reference: Saved Query Model](../reference/saved-query-model.md)

## Source grounding
- STATUS: CODE_CONFIRMED (route classes in RBAC audit), INFERRED_FROM_STRUCTURE (exact paths)
- Sources:
  - `.claude/audits/backend-audit.md` (Task 6 — query_tree_routes.py RBAC retrofit)
  - `app/routes/` (query_tree_routes.py listed but not found at standard path — NEEDS_VERIFICATION)
