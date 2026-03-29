from __future__ import annotations

from typing import Callable

from app.services.shared_ai.context import PipelineContext
from app.services.shared_ai.executor import PipelineExecutor
from app.services.shared_ai.graph import PipelineDefinition
from app.services.shared_ai.node import BasePipelineNode


class DispatchSubgraphNode(BasePipelineNode):
    def __init__(
        self,
        *,
        definition_factory: Callable[[PipelineContext], PipelineDefinition],
        name: str = "dispatch_subgraph",
        requires: tuple[str, ...] = (),
        produces: tuple[str, ...] = (),
        executor: PipelineExecutor | None = None,
    ) -> None:
        self.name = name
        self.requires = tuple(requires)
        self.produces = tuple(produces)
        self._definition_factory = definition_factory
        self._executor = executor or PipelineExecutor()

    def run(self, context: PipelineContext) -> PipelineContext:
        definition = self._definition_factory(context)
        if not isinstance(definition, PipelineDefinition):
            raise TypeError(f"{self.name} expected PipelineDefinition from definition_factory.")

        context.add_debug(
            self.name,
            {
                "subgraph": definition.name,
                "requires": list(self.requires),
                "produces": list(self.produces),
            },
        )
        return self._executor.execute(definition, context)
