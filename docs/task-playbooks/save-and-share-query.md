# Goal: Save and Share a Query

## Audience

Analysts who have built a query in Query Studio and want to preserve and collaborate on it.

## What you need

- A working query in Query Studio
- `query_studio:user` role

## Steps

1. **Run your query and verify results are correct**
   Before saving, confirm the query returns the expected data.

2. **Save the query**
   Use the save action in Query Studio. The frontend calls `SavedQueryCreate` (route in `query_tree_routes.py`). Provide:
   - A name (required)
   - A folder (optional — if none, query is saved to root)

3. **Organize into a folder (optional)**
   Create a folder to organize related queries. Folders can be nested. Folders support rename, move, trash, and purge operations.

4. **Share with colleagues**
   From the saved query, open the share panel. `SavedQueryShares` (GET/POST/DELETE) manages share records. Add users by their ID or username (NEEDS_VERIFICATION: exact share UI flow). Shared users can view and execute the query.

5. **Verify the share**
   Confirm the shared user can see the query in their query tree.

## What happens next

The saved query is now persisted and accessible to shared users. It can be:
- Attached to a skill for automated execution
- Referenced by ForgeInsights for conversational analysis
- Executed on demand from the query tree

## Common issues

- **Folder doesn't appear** — refresh the query tree or check workspace permissions.
- **Share not visible to recipient** — verify the recipient's `query_studio:user` role is active.
- **Saved query not running correctly** — the plan is persisted at save time. If the underlying schema changed, re-run the planner and re-save.

## Related docs

- [Concepts: Saved Queries](../concepts/saved-queries.md)
- [User Guide: Saved Queries Overview](../user-guides/saved-queries-overview.md)

## Source grounding
- STATUS: INFERRED_FROM_STRUCTURE, NEEDS_VERIFICATION
- Sources:
  - `.claude/audits/backend-audit.md` (Task 6: SavedQueryCreate, SavedQueryShares)
