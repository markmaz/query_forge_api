from __future__ import annotations

from typing import Protocol

from app.services.forge_match.session_pipeline_artifacts import (
    ForgeMatchSessionExecutionArtifact,
    ForgeMatchSessionResultArtifact,
    ForgeMatchSessionWorkArtifact,
)
from app.services.shared_ai.context import PipelineContext
from app.services.shared_ai.node import BasePipelineNode


class SessionPreparationAdapter(Protocol):
    def prepare(self, *, context: PipelineContext) -> ForgeMatchSessionWorkArtifact:
        ...


class SessionExecutionAdapter(Protocol):
    def execute(
        self,
        *,
        context: PipelineContext,
        work: ForgeMatchSessionWorkArtifact,
    ) -> ForgeMatchSessionExecutionArtifact:
        ...


class SessionFinalizationAdapter(Protocol):
    def finalize(
        self,
        *,
        context: PipelineContext,
        work: ForgeMatchSessionWorkArtifact,
        execution: ForgeMatchSessionExecutionArtifact,
    ) -> ForgeMatchSessionResultArtifact:
        ...


class PrepareSessionRunNode(BasePipelineNode):
    def __init__(
        self,
        *,
        adapter: SessionPreparationAdapter,
        name: str = "prepare_session_run",
        output_artifact_key: str = "session_work",
    ) -> None:
        self.name = name
        self.requires = ()
        self.produces = (output_artifact_key,)
        self._adapter = adapter
        self._output_artifact_key = output_artifact_key

    def run(self, context: PipelineContext) -> PipelineContext:
        artifact = self._adapter.prepare(context=context)
        if not isinstance(artifact, ForgeMatchSessionWorkArtifact):
            raise TypeError(f"{self.name} expected ForgeMatchSessionWorkArtifact from preparation adapter.")
        context.set_artifact(self._output_artifact_key, artifact)
        context.add_debug(
            self.name,
            {
                "source_total": artifact.source_total,
            },
        )
        return context


class ExecuteSessionRowsNode(BasePipelineNode):
    def __init__(
        self,
        *,
        adapter: SessionExecutionAdapter,
        name: str = "execute_session_rows",
        work_artifact_key: str = "session_work",
        output_artifact_key: str = "session_execution",
    ) -> None:
        self.name = name
        self.requires = (work_artifact_key,)
        self.produces = (output_artifact_key,)
        self._adapter = adapter
        self._work_artifact_key = work_artifact_key
        self._output_artifact_key = output_artifact_key

    def run(self, context: PipelineContext) -> PipelineContext:
        work = context.get_artifact(self._work_artifact_key, node_name=self.name)
        if not isinstance(work, ForgeMatchSessionWorkArtifact):
            raise TypeError(f"{self.name} expected ForgeMatchSessionWorkArtifact at '{self._work_artifact_key}'.")
        artifact = self._adapter.execute(context=context, work=work)
        if not isinstance(artifact, ForgeMatchSessionExecutionArtifact):
            raise TypeError(f"{self.name} expected ForgeMatchSessionExecutionArtifact from execution adapter.")
        context.set_artifact(self._output_artifact_key, artifact)
        context.add_debug(
            self.name,
            {
                "status": artifact.status,
                "analyzed_count": artifact.analyzed_count,
                "skipped_count": artifact.skipped_count,
                "failed_count": artifact.failed_count,
            },
        )
        return context


class FinalizeSessionRunNode(BasePipelineNode):
    def __init__(
        self,
        *,
        adapter: SessionFinalizationAdapter,
        name: str = "finalize_session_run",
        work_artifact_key: str = "session_work",
        execution_artifact_key: str = "session_execution",
        output_artifact_key: str = "session_result",
    ) -> None:
        self.name = name
        self.requires = (work_artifact_key, execution_artifact_key)
        self.produces = (output_artifact_key,)
        self._adapter = adapter
        self._work_artifact_key = work_artifact_key
        self._execution_artifact_key = execution_artifact_key
        self._output_artifact_key = output_artifact_key

    def run(self, context: PipelineContext) -> PipelineContext:
        work = context.get_artifact(self._work_artifact_key, node_name=self.name)
        execution = context.get_artifact(self._execution_artifact_key, node_name=self.name)
        if not isinstance(work, ForgeMatchSessionWorkArtifact):
            raise TypeError(f"{self.name} expected ForgeMatchSessionWorkArtifact at '{self._work_artifact_key}'.")
        if not isinstance(execution, ForgeMatchSessionExecutionArtifact):
            raise TypeError(
                f"{self.name} expected ForgeMatchSessionExecutionArtifact at '{self._execution_artifact_key}'."
            )
        artifact = self._adapter.finalize(context=context, work=work, execution=execution)
        if not isinstance(artifact, ForgeMatchSessionResultArtifact):
            raise TypeError(f"{self.name} expected ForgeMatchSessionResultArtifact from finalization adapter.")
        context.set_artifact(self._output_artifact_key, artifact)
        context.add_debug(
            self.name,
            {
                "status": str(artifact.payload.get("status") or ""),
                "result_count": int(artifact.payload.get("result_count") or 0),
            },
        )
        return context
