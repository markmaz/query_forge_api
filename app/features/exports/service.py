from __future__ import annotations

from app.services.execution_service import ExecutionService
from app.services.exports.export_materialization_service import ExportMaterializationService
from app.services.exports.export_request_service import ExportRequestService


class ExportsFeatureService:
    def __init__(
        self,
        *,
        export_request_service_factory=ExportRequestService,
        export_materialization_service_factory=ExportMaterializationService,
    ) -> None:
        self._export_request_service_factory = export_request_service_factory
        self._export_materialization_service_factory = export_materialization_service_factory

    def prepare_excel_export(self, *, workspace_id: str, payload: dict, **service_kwargs):
        return self._export_request_service_factory(**service_kwargs).prepare_excel_export(
            workspace_id=workspace_id,
            payload=payload,
        )

    def build_excel_download(self, *, workspace_id: str, token: str, **service_kwargs):
        return self._export_materialization_service_factory(**service_kwargs).build_excel_download(
            workspace_id=workspace_id,
            token=token,
        )


class ExecutionsFeatureService:
    def __init__(self, *, execution_service_factory=ExecutionService) -> None:
        self._execution_service_factory = execution_service_factory

    def start(self, workspace_id: str, payload: dict, query_params: dict):
        return self._execution_service_factory().start(workspace_id, payload, query_params)

    def status(self, workspace_id: str, job_id: str):
        return self._execution_service_factory().status(workspace_id, job_id)

    def cancel(self, workspace_id: str, job_id: str):
        return self._execution_service_factory().cancel(workspace_id, job_id)

    def results(self, workspace_id: str, job_id: str):
        return self._execution_service_factory().results(workspace_id, job_id)
