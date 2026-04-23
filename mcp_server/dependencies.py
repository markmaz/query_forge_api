from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional

from mcp.server.fastmcp import Context

from .audit import MCPAuditLogger
from .auth import AuthResolver, FastMCPRequestAuthenticator
from .config import MCPSettings
from .context import RequestContext


@dataclass
class MCPDependencies:
    settings: MCPSettings
    auth_resolver: Optional[AuthResolver] = None
    audit_logger: Optional[MCPAuditLogger] = None
    domain_adapter_factory: Optional[Callable[[], Any]] = None
    dictionary_adapter_factory: Optional[Callable[[], Any]] = None
    planner_adapter_factory: Optional[Callable[[], Any]] = None
    execution_adapter_factory: Optional[Callable[[], Any]] = None
    saved_query_adapter_factory: Optional[Callable[[], Any]] = None
    policy_resource_factory: Optional[Callable[[], Any]] = None
    semantic_resource_factory: Optional[Callable[[], Any]] = None

    def resolve_request_context(self, workspace_id: str, ctx: Context) -> RequestContext:
        resolver = self.auth_resolver or FastMCPRequestAuthenticator().resolve
        return resolver(workspace_id, ctx)

    def get_audit_logger(self) -> MCPAuditLogger:
        if self.audit_logger is None:
            self.audit_logger = MCPAuditLogger(enabled=self.settings.audit_logging)
        return self.audit_logger

    def get_domain_adapter(self):
        if self.domain_adapter_factory is not None:
            return self.domain_adapter_factory()
        from .adapters.domain_adapter import DomainAdapter
        return DomainAdapter()

    def get_dictionary_adapter(self):
        if self.dictionary_adapter_factory is not None:
            return self.dictionary_adapter_factory()
        from .adapters.dictionary_adapter import DictionaryAdapter
        return DictionaryAdapter()

    def get_planner_adapter(self):
        if self.planner_adapter_factory is not None:
            return self.planner_adapter_factory()
        from .adapters.planner_adapter import PlannerAdapter
        return PlannerAdapter(settings=self.settings)

    def get_saved_query_adapter(self):
        if self.saved_query_adapter_factory is not None:
            return self.saved_query_adapter_factory()
        from .adapters.saved_query_adapter import SavedQueryAdapter
        return SavedQueryAdapter(settings=self.settings)

    def get_execution_adapter(self):
        if self.execution_adapter_factory is not None:
            return self.execution_adapter_factory()
        from .adapters.execution_adapter import ExecutionAdapter
        return ExecutionAdapter(planner_adapter=self.get_planner_adapter())

    def get_policy_resource(self):
        if self.policy_resource_factory is not None:
            return self.policy_resource_factory()
        from .resources.policies import PlannerPolicyResource
        return PlannerPolicyResource()

    def get_semantic_resource(self):
        if self.semantic_resource_factory is not None:
            return self.semantic_resource_factory()
        from .resources.semantic_registry import SemanticRegistryResource
        return SemanticRegistryResource()
