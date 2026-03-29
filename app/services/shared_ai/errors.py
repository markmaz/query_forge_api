from __future__ import annotations


class SharedAIPipelineError(RuntimeError):
    """Base error for shared AI pipeline execution."""


class PipelineGraphValidationError(SharedAIPipelineError):
    """Raised when a pipeline graph definition is invalid."""


class MissingArtifactError(SharedAIPipelineError):
    """Raised when a node requires an artifact that is not present."""

    def __init__(self, *, node_name: str, artifact_key: str) -> None:
        super().__init__(f"Node '{node_name}' requires missing artifact '{artifact_key}'.")
        self.node_name = node_name
        self.artifact_key = artifact_key


class PipelineNodeExecutionError(SharedAIPipelineError):
    """Raised when a node fails during execution."""

    def __init__(self, *, node_name: str, original_error: Exception) -> None:
        super().__init__(f"Node '{node_name}' failed: {original_error}")
        self.node_name = node_name
        self.original_error = original_error
