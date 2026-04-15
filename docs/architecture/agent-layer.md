# Architecture: Agent Layer

## Purpose

The Agent Layer is a planned extension of the Skills system that introduces goal-driven orchestrations with durable state, multi-step decisioning, and skill composition. It is designed to sit on top of the existing Skills execution primitives.

## Status

NEEDS_VERIFICATION: The Agent Layer was fully specified in `specs/queryforge_agent_layer_codex_spec.md` but no implementation was found during code inventory. This document describes the intended architecture per the spec. Verify actual implementation status.

## Components (per spec)

| Component | Description |
|-----------|-------------|
| Agent Definition | Named goal-driven object with skill compositions, decision logic, schedule |
| Agent Template | Pre-built best-practice agent compositions |
| Agent State | Durable per-agent state (last run, snapshot, alert history, change detection) |
| Agent Executor | Orchestrates multi-step skill execution with conditional decisioning |
| Skills | Existing execution primitives (threshold_alert, ai_summary_digest, etc.) |

## Flow (per spec)

1. **Trigger** — scheduled (Celery) or event-driven
2. **Load agent state** — fetch last run, prior snapshot, alert history
3. **Run query** — execute the agent's associated saved query
4. **Inspect results** — compare to prior snapshot (change detection)
5. **Evaluate conditions** — apply decision logic (threshold, freshness, material change)
6. **Summarize** (optional) — call LLM to generate narrative
7. **Deliver** — use delivery skills (email, webhook) if conditions met
8. **Update state** — persist new snapshot, alert state, run timestamp
9. **Record execution** — audit log

## Inputs / Outputs

**Agent run inputs:**
- Agent definition (goal, skill composition, decision config)
- Prior state
- Current query results

**Agent run outputs:**
- Updated state
- Delivery artifacts (emails sent, webhooks fired)
- Audit record
- Execution status

## Important decisions (per spec)

- **Skills are unchanged** — agents compose skills, do not replace them
- **LLMs are tools, not orchestrators** — LLMs summarize/classify; deterministic code owns orchestration
- **State is required** — stateless execution is explicitly rejected for agents
- **Human-safe** — agents are not autonomous; they execute defined logic against saved queries

## Related systems

- [Skills](../concepts/skills.md)
- [Planner Pipeline](planner-pipeline.md)
- [Concepts: Agents](../concepts/agents.md)

## Source grounding
- STATUS: SPEC_CONFIRMED (design), NEEDS_VERIFICATION (implementation)
- Sources:
  - `specs/queryforge_agent_layer_codex_spec.md`
