from __future__ import annotations

from typing import Any, Literal, TypedDict

WorkflowNodeType = Literal[
    "schedule_trigger",
    "webhook_trigger",
    "file_watch_trigger",
    "intake",
    "scoring",
    "filter",
    "ranking",
    "human_task",
    "matching",
    "notification",
    "wait",
    "end",
    "decision",
    "event_capture",
    "iterator",
    "query_extract",
    "export",
    "import",
    "map_transform",
    "approval",
]


class WorkflowPosition(TypedDict):
    x: int
    y: int


class WorkflowViewport(TypedDict):
    x: int
    y: int
    zoom: float


class WorkflowNode(TypedDict):
    id: str
    type: WorkflowNodeType
    label: str
    position: WorkflowPosition
    data: dict[str, Any]


class WorkflowEdge(TypedDict, total=False):
    id: str
    source: str
    target: str
    label: str


class WorkflowGraphRequired(TypedDict):
    nodes: list[WorkflowNode]
    edges: list[WorkflowEdge]


class WorkflowGraph(WorkflowGraphRequired, total=False):
    viewport: WorkflowViewport


class WorkflowDefinitionGovernance(TypedDict, total=False):
    owner_user_id: str | None
    lifecycle: str
    run_as_principal: dict[str, Any]
    effective_permissions: dict[str, Any]


class WorkflowDefinition(WorkflowDefinitionGovernance):
    id: str
    name: str
    description: str
    status: str
    graph: WorkflowGraph


class WorkflowValidationResult(TypedDict):
    valid: bool
    errors: list[str]
    warnings: list[str]


class WorkflowRunEvent(TypedDict):
    id: str
    event_type: str
    node_id: str | None
    message: str
    timestamp: str
    data: dict[str, Any]
