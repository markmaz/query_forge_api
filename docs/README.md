# QueryForge Documentation

## How these docs were generated

These docs were generated on 2026-03-31 by an automated agent that performed a systematic inventory of:
- All route files under `app/routes/`
- All service directories under `app/services/`
- All skill files under `app/skills/`
- All task files under `app/tasks/`
- Frontend feature modules under `query-forge-ui/src/features/`
- Existing specs under `specs/` and `docs/superpowers/specs/`
- Audit files under `.claude/audits/`
- Implementation notes in `docs/plans/`

No behavior was invented. Every claim is grounded in code, specs, or existing documentation. Uncertain areas are explicitly marked.

## How to maintain them

1. When a new route or feature is added, update the relevant concept and reference docs.
2. When a spec changes, update the architecture doc and mark changed sections.
3. Use the confidence level system to signal freshness.
4. Run a re-inventory periodically (update `_inventory/docs_inventory.md` and `_inventory/gaps_and_questions.md`).

## Confidence levels explained

| Level | Meaning |
|-------|---------|
| **SPEC_CONFIRMED** | Behavior matches a spec file in `specs/` or `docs/superpowers/specs/` |
| **CODE_CONFIRMED** | Behavior confirmed by reading actual source code |
| **TEST_CONFIRMED** | Behavior confirmed by test files |
| **INFERRED_FROM_STRUCTURE** | Inferred from file/folder names, namespace names, obvious patterns |
| **NEEDS_VERIFICATION** | Uncertain — requires a human to verify against the running system |

## Folder structure

```
docs/
  getting-started/     — onboarding, first query
  concepts/            — what each major feature is and why it exists
  user-guides/         — feature walkthroughs for end users
  task-playbooks/      — step-by-step task guides
  admin/               — workspace setup, user management, deployment
  architecture/        — internal system design, pipelines, layers
  reference/           — data models, route groups, response objects
  troubleshooting/     — diagnosis and fix guides
  _inventory/          — machine-readable feature and gap inventory
  _templates/          — doc templates for new contributors
  plans/               — implementation plans (pre-existing)
  superpowers/         — superpowers specs (pre-existing)
```

## How to contribute

1. Pick the appropriate template from `_templates/`.
2. Fill in all sections. Do not leave placeholder text.
3. Set the correct confidence level.
4. List all source files you read.
5. Add your doc to the inventory CSV (`_inventory/docs_inventory.csv`).
6. If you find a gap, add it to `_inventory/gaps_and_questions.md`.
