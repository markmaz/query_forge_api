from __future__ import annotations

from app.services.query_tree.saved_query_library_service import SavedQueryLibraryService


class SavedQueriesFeatureService:
    def __init__(self, *, library_service_factory=SavedQueryLibraryService) -> None:
        self._library_service_factory = library_service_factory

    def build_library_service(
        self,
        *,
        workspace_id: str,
        user_id: str,
        allow_publish: bool = False,
        allow_delete_query: bool = False,
        allow_manage: bool = False,
    ):
        return self._library_service_factory(
            workspace_id=workspace_id,
            user_id=user_id,
            allow_publish=allow_publish,
            allow_delete_query=allow_delete_query,
            allow_manage=allow_manage,
        )
