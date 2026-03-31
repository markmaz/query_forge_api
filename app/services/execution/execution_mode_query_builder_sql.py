from __future__ import annotations

from app.services.execution.execution_mode_query_builder import ExecutionModePreparedSql


class ExecutionModeQueryBuilderSql:
    def prepare(self, *, raw_sql: str) -> ExecutionModePreparedSql:
        return ExecutionModePreparedSql(
            sql=raw_sql,
            params={},
            sql_rendered=raw_sql,
            count_sql=None,
        )
