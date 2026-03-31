from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional, Type


@dataclass(frozen=True)
class ExecutionModePreparedSql:
    sql: str
    params: Dict[str, Any]
    sql_rendered: Optional[str]
    count_sql: Optional[str]


class ExecutionModeQueryBuilder:
    def __init__(
        self,
        *,
        query_forge_service_cls: Type[Any],
        domain_resolver_factory: Callable[[str], Any],
    ) -> None:
        self._query_forge_service_cls = query_forge_service_cls
        self._domain_resolver_factory = domain_resolver_factory

    def prepare(
        self,
        *,
        workspace_id: str,
        sql_exec: Any,
        sql_json: Dict[str, Any],
        mode: str,
        limit: int,
        offset: int,
    ) -> ExecutionModePreparedSql:
        domain_resolver = self._domain_resolver_factory(workspace_id)
        service = self._query_forge_service_cls(executor=sql_exec, domain_resolver=domain_resolver)
        prepared = service.prepare(raw_query=sql_json, mode=mode, limit=limit, offset=offset)
        return ExecutionModePreparedSql(
            sql=prepared.sql,
            params=prepared.params,
            sql_rendered=prepared.qf_rendered_sql,
            count_sql=prepared.qf_count_sql,
        )
