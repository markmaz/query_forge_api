from __future__ import annotations


class SavedQueriesPolicy:
    def __init__(self, *, role_resolver) -> None:
        self._role_resolver = role_resolver

    def effective_roles(self, *, user_id: str, workspace_id: str | None = None) -> set[str]:
        return set(self._role_resolver(user_id, workspace_id=workspace_id))

    @staticmethod
    def can_publish_to_library(roles: set[str]) -> bool:
        return bool({"workspace_admin", "library_admin", "super_admin"} & roles)

    @staticmethod
    def can_delete_library_queries(roles: set[str]) -> bool:
        return bool({"workspace_admin", "library_admin", "super_admin"} & roles)

    @staticmethod
    def can_manage_library_items(roles: set[str]) -> bool:
        return bool({"workspace_admin", "library_admin", "super_admin"} & roles)
