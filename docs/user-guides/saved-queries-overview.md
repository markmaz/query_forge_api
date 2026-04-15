# Saved Queries User Guide

## What it is

Saved queries let you preserve a query plan for repeated execution. They live in a folder hierarchy (the query tree) and can be shared with other users or attached to skills for automated monitoring.

## Who uses it

Users with `query_studio:user` role in a workspace where `query_studio` is entitled.

## What you can do

### Saving a query
After building and running a query in Query Studio, use the save action to persist it to the query tree. Provide a name and optionally select a folder.

### Folder organization
Create folders to organize saved queries. Folders support:
- Rename
- Move
- Trash (soft delete, restorable)
- Purge (permanent delete)

### Recent queries
The query tree interface shows recently accessed queries for quick navigation.

### Sharing
Share a saved query with specific colleagues. Shares are managed per-query and control who can view and execute the query.

### Attaching skills
From a saved query, you can attach a Skill (threshold alert, AI summary digest, data freshness check, etc.) that will run the query automatically on a schedule. See the [Skills concept](../concepts/skills.md) for details.

## Status notes

NEEDS_VERIFICATION: The exact frontend routes for the query tree (folder/query CRUD) were not found in `app/routes/` during inventory. They are listed in the RBAC audit as `query_tree_routes.py` but this file was not present in the route listing. Verify whether these routes are registered under a different file or path.

## Related docs

- [Concepts: Saved Queries](../concepts/saved-queries.md)
- [Task Playbook: Save and Share a Query](../task-playbooks/save-and-share-query.md)
- [Concepts: Skills](../concepts/skills.md)

## Source grounding
- STATUS: INFERRED_FROM_STRUCTURE, NEEDS_VERIFICATION
- Sources:
  - `.claude/audits/backend-audit.md` (Task 6: query_tree_routes.py referenced)
  - `app/routes/` (query_tree_routes.py not found in directory listing)
