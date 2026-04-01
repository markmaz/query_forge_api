# Agents

## What it is

Agents are goal-driven orchestrations built on top of the Skills system. While a Skill is a single action block, an Agent is an orchestrator with a goal, durable state, execution history, and multi-step decisioning logic. Agents compose Skills to perform goal-based monitoring and reporting workflows.

## Why it matters

Skills handle individual actions (alert if threshold breached, send email). Agents handle compound goals: "Monitor weekly attendance health — run query, inspect results, detect trigger conditions, summarize findings, deliver to channels, update state." Agents are the first class of automation that can maintain context over time and make conditional decisions.

## Who uses it

- **Advanced users / power users** — set up goal-based monitoring workflows.
- **Skills admins** — manage agent definitions and templates.

## Key concepts

The Agent Layer spec (SPEC_CONFIRMED: `specs/queryforge_agent_layer_codex_spec.md`) defines:

### Agent Definition
A named, goal-oriented object with:
- A goal description (e.g., "Monitor attendance health")
- A list of skills to compose
- State tracking (last run, last result snapshot, prior alerts, change detection history)
- Decision logic (when to notify, whether results changed materially, whether freshness failed)
- Schedule and trigger configuration

### Agent Templates
Pre-built agent templates that users can instantiate. Templates encode best-practice compositions of skills for common monitoring goals.

### Agent State
Agents maintain durable run state:
- `last_run` timestamp
- `last_result_snapshot`
- `prior_highlights`
- `prior_alert_state`
- `change_detection_history`

### Agent Execution
Multi-step orchestration:
1. Run query
2. Inspect results
3. Detect trigger conditions
4. Summarize findings (optional, via LLM)
5. Deliver to channels (via delivery skills)
6. Update state

### Distinction from Skills
- **Skill** = a tool / block (single action, stateless execution)
- **Agent** = an orchestrator with a goal, state, and execution lifecycle

Per the spec: LLMs may summarize or classify severity within an agent run, but they do not own the orchestration core — execution is deterministic.

## Status

NEEDS_VERIFICATION: The Agent Layer spec was written as a design target (`specs/queryforge_agent_layer_codex_spec.md`). Implementation status is not confirmed from code inventory. The spec states this is a "comprehensive V1, not a speculative AI agent toy" but no agent-specific route files were found in `app/routes/` during inventory. Check if agent routes exist under a different name or if implementation is pending.

## Related features

- [Skills](skills.md)
- [Saved Queries](saved-queries.md)
- [User Guide: Agents Overview](../user-guides/agents-overview.md)

## Source grounding
- STATUS: SPEC_CONFIRMED (design), NEEDS_VERIFICATION (implementation status)
- Sources:
  - `specs/queryforge_agent_layer_codex_spec.md`
  - `app/routes/` (no agent-specific routes found in inventory)
