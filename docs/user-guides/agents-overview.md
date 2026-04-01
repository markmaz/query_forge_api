# Agents User Guide

## What it is

Agents are goal-driven automations that compose multiple Skills to accomplish a monitoring or reporting objective over time. An agent has a goal, maintains state across runs, and makes conditional decisions about whether to notify, summarize, or take other actions.

## Status

NEEDS_VERIFICATION: The Agent Layer was designed as a V1 in `specs/queryforge_agent_layer_codex_spec.md`. However, no agent-specific route files or service modules were confirmed during the codebase inventory. This guide describes the intended behavior per the spec. Verify implementation status before using this as a reference for a deployed system.

## Who uses it

Users with skills access in a workspace where skills are entitled. Agent management likely requires `skills:admin` role (INFERRED_FROM_SPEC).

## What you can do (per spec)

### Create an agent from a template
Browse available agent templates that encode best-practice skill compositions for common goals (e.g., "Monitor weekly attendance health", "Watch enrollment changes").

### Define a custom agent
- Set a goal description
- Choose which skills to compose (threshold alert, AI summary digest, data freshness check, delivery)
- Configure decision logic (when to notify, threshold for material change, freshness window)
- Set schedule or trigger

### Review agent state
Each agent maintains:
- Last run timestamp
- Last result snapshot
- Prior highlights
- Alert state history
- Change detection history

### View execution history
See past agent runs with audit trail of decisions made at each step.

### Audit and explainability
Agent runs are auditable — every step (query execution, condition evaluation, delivery decision) is logged.

## How agents differ from skills

| | Skill | Agent |
|-|-------|-------|
| **Abstraction** | A single action block | A goal-driven orchestrator |
| **State** | Stateless (per execution) | Maintains durable run state |
| **Decision logic** | Fixed threshold/config | Conditional multi-step logic |
| **Composition** | Single skill type | Composes multiple skills |

## Related docs

- [Concepts: Agents](../concepts/agents.md)
- [Concepts: Skills](../concepts/skills.md)
- [Spec: Agent Layer](../../specs/queryforge_agent_layer_codex_spec.md)

## Source grounding
- STATUS: SPEC_CONFIRMED (design), NEEDS_VERIFICATION (implementation)
- Sources:
  - `specs/queryforge_agent_layer_codex_spec.md`
