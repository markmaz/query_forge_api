# Shared AI Pipelines

## What it is

The shared AI pipeline architecture (`app/services/shared_ai/`) is an internal reusable framework that allows multiple QueryForge AI workflows (the planner and ForgeMatch) to share pipeline nodes instead of maintaining separate, drifting implementations.

## Why it matters

Before this architecture, the planner and ForgeMatch had independent implementations of signal extraction, capability resolution, and reranking. Improvements made to one did not benefit the other. The shared AI pipeline creates a common execution framework so that new improvements are automatically available to all pipelines that use it.

## Who uses it

Internal — not directly user-facing. The planner domain service and ForgeMatch mapping service both compose pipelines from shared nodes.

## Key concepts

### PipelineDefinition
A named DAG of nodes and edges (`app/services/shared_ai/graph.py`). Validated at construction time — cycles, unknown nodes, and missing start nodes are all caught. Fields: `name`, `nodes` (dict), `edges` (list of `PipelineEdge`), `start_nodes` (list).

### PipelineNode
An abstract execution unit. Nodes receive a context artifact and produce output artifacts. Implemented in `app/services/shared_ai/node.py`.

### PipelineEdge
A directed connection between nodes with an optional condition. Conditions allow conditional branching in the execution graph.

### Executor
`app/services/shared_ai/executor.py` — walks the graph, dispatches nodes in order, collects artifacts, and builds a trace. Supports nested subgraph dispatch with lineage-aware trace entries.

### Artifacts
`app/services/shared_ai/artifacts.py` — typed data objects that flow between nodes (e.g., normalized prompt, signal set, candidates, reranked candidates).

### Tracing
`app/services/shared_ai/tracing.py` — trace serialization for debugging and pipeline profile retrieval.

### Registry
`app/services/shared_ai/registry.py` — registry of available shared pipeline nodes.

### Adapters
`app/services/shared_ai/adapters/` — adapters that connect shared nodes to planner-domain and forge-match specific data structures.

### Conditions
`app/services/shared_ai/conditions.py` — condition evaluators for conditional edge branching.

### Implementation Status
All 8 phases complete as of 2026-03-28 (SPEC_CONFIRMED):
- Phase 1: Core shared_ai framework
- Phase 2: Shared signal and capability nodes
- Phase 3: Policy reranking node
- Phase 4: ForgeMatch candidate reranking via shared executor
- Phase 5: Planner domain selection/rerank via shared executor
- Phase 6: Explicit pipeline definition builders
- Phase 7: Nested subgraph dispatch
- Phase 8: Full integration (details NEEDS_VERIFICATION)

## Related systems

- [Planner](planner.md)
- [ForgeMatch](forgematch.md)
- [Architecture: Shared AI Pipeline](../architecture/shared-ai-pipeline.md)

## Source grounding
- STATUS: SPEC_CONFIRMED (phases 1-8), CODE_CONFIRMED (file structure)
- Sources:
  - `specs/queryforge_shared_ai_pipeline_architecture_spec.md`
  - `app/services/shared_ai/graph.py`
  - `app/services/shared_ai/` (directory listing)
