# Architecture: Shared AI Pipeline

## Purpose

The shared AI pipeline (`app/services/shared_ai/`) is a reusable execution framework for composing AI workflows from typed pipeline nodes. It allows the planner and ForgeMatch to share signal extraction, capability resolution, and reranking logic instead of maintaining separate, drifting implementations.

## Components

| Component | File | Description |
|-----------|------|-------------|
| `PipelineDefinition` | `graph.py` | Named DAG of nodes + edges. Validated at construction time. |
| `PipelineEdge` | `graph.py` | Directed connection with optional condition |
| `PipelineNode` | `node.py` | Abstract execution unit |
| `Executor` | `executor.py` | Walks the graph, dispatches nodes, collects artifacts, builds trace |
| Artifacts | `artifacts.py` | Typed data objects flowing between nodes |
| Tracing | `tracing.py` | Step-by-step trace serialization |
| Registry | `registry.py` | Available shared pipeline nodes |
| Adapters | `adapters/` | Connect shared nodes to pipeline-specific data structures |
| Conditions | `conditions.py` | Condition evaluators for conditional edge branching |
| Errors | `errors.py` | `PipelineGraphValidationError` and related exceptions |
| Context | `context.py` | Execution context object |
| Node implementations | `nodes/` | Concrete shared node implementations (signal, capability, rerank) |

## Flow

1. A pipeline consumer (e.g., `PlannerDomainService` or `ForgeMatchMappingService`) builds a `PipelineDefinition` using a definition builder.
2. The definition specifies which shared nodes to run and in what order (DAG).
3. The `Executor` validates the definition (no cycles, all referenced nodes exist).
4. The executor dispatches start nodes, passing typed artifacts between nodes along edges.
5. Conditional edges allow branching based on artifact contents.
6. Nested subgraph dispatch is supported — a node can itself launch a sub-pipeline, with lineage-aware trace entries.
7. The executor returns final artifacts and a trace.

## Graph validation

At construction time, `validate_pipeline_definition()` checks:
- Name is non-empty
- At least one node
- At least one start node
- All start nodes exist in the node map
- All edge `from_node` and `to_node` refer to known nodes
- No cycles (DFS-based detection)

If validation fails, `PipelineGraphValidationError` is raised before any execution.

## Inputs / Outputs

**Inputs to a pipeline execution:**
- Initial artifact(s) (e.g., normalized prompt + workspace context)
- `PipelineDefinition`

**Outputs:**
- Final artifact set
- Pipeline trace (list of `PipelineTraceEntry` objects with node name, timing, and intermediate data)

## Important decisions

- **Explicit graph, not implicit code** — pipelines are defined as data structures, making the execution order inspectable and testable.
- **Typed artifacts** — data between nodes is typed, not generic dicts, so node contracts are clear.
- **Cycle detection** — enforced at definition time, not execution time.
- **Lineage-aware tracing** — nested subgraphs create trace entries with parent-child lineage for debugging.

## Related systems

- [Planner Pipeline](planner-pipeline.md)
- [ForgeMatch](../concepts/forgematch.md)
- [Concepts: Shared AI Pipelines](../concepts/shared-ai-pipelines.md)

## Source grounding
- STATUS: CODE_CONFIRMED
- Sources:
  - `app/services/shared_ai/graph.py`
  - `app/services/shared_ai/` (directory listing)
  - `specs/queryforge_shared_ai_pipeline_architecture_spec.md`
