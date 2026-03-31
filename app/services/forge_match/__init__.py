"""ForgeMatch mapping workflow services."""

__all__ = ["ForgeMatchMappingService"]


def __getattr__(name: str):
    if name == "ForgeMatchMappingService":
        from .mapping_service import ForgeMatchMappingService

        return ForgeMatchMappingService
    raise AttributeError(name)
