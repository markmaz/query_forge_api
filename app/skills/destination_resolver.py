"""
app/skills/destination_resolver.py

Resolves a destination_id to a decrypted config dict at skill execution time.
Called by each delivery channel that uses a destination reference.

Usage in delivery channels:
    from app.skills.destination_resolver import resolve_destination
    config = resolve_destination(destination_id, workspace_id)
    # config is the decrypted dict — e.g. {"webhook_url": "https://..."}

Also handles backwards compatibility: if a channel config contains a raw
webhook_url instead of destination_id, it is passed through unchanged.
This allows existing skills to work without migration.
"""

from __future__ import annotations

import logging
from typing import Any

from app.extensions import db
from app.models.domain.destinations import WorkspaceDestination

logger = logging.getLogger(__name__)


def _query_destination(*, destination_id: int, workspace_id: int, active_only: bool) -> WorkspaceDestination | None:
    query = getattr(WorkspaceDestination, "query", None)
    if query is not None:
        filters = {"id": destination_id, "workspace_id": workspace_id}
        if active_only:
            filters["is_active"] = True
        return query.filter_by(**filters).first()

    session_query = db.session.query(WorkspaceDestination).filter_by(
        id=destination_id,
        workspace_id=workspace_id,
    )
    if active_only:
        session_query = session_query.filter_by(is_active=True)
    return session_query.first()


def resolve_destination(destination_id: int, workspace_id: int) -> dict[str, Any]:
    """
    Resolve a destination_id to its decrypted config dict.

    Raises:
        ValueError — if destination not found, inactive, or belongs to different workspace
    """
    dest = _query_destination(
        destination_id=destination_id,
        workspace_id=workspace_id,
        active_only=True,
    )

    if not dest:
        raise ValueError(
            f"Destination {destination_id} not found or inactive "
            f"in workspace {workspace_id}."
        )

    config = dest.get_config()

    # Record usage asynchronously — don't let tracking failures block delivery
    try:
        dest.record_usage()
        db.session.commit()
    except Exception as exc:
        logger.warning("Failed to record destination usage for id=%s: %s", destination_id, exc)

    return config


def resolve_channel_config(channel_config: dict, workspace_id: int) -> dict[str, Any]:
    """
    Backwards-compatible resolution for skill channel configs.

    If channel_config contains destination_id → resolve it.
    If channel_config contains raw webhook_url → pass through unchanged.
    This allows skills created before the Destinations feature to keep working.

    Args:
        channel_config: the channel dict from a skill's config.channels list
        workspace_id:   current workspace

    Returns:
        Resolved config dict ready for delivery channel .send()
    """
    if "destination_id" in channel_config:
        resolved = resolve_destination(channel_config["destination_id"], workspace_id)
        # Merge any non-sensitive overrides from channel_config (e.g. severity)
        return {**resolved, **{
            k: v for k, v in channel_config.items()
            if k not in ("destination_id", "type")
        }}

    # Backwards compat — raw config passes through
    logger.debug(
        "Channel config uses raw credentials (no destination_id) — "
        "consider migrating to a named Destination."
    )
    return channel_config


def validate_destination_ref(destination_id: int, workspace_id: int) -> list[str]:
    """
    Validate that a destination_id is usable. Returns list of error strings.
    Called during skill config validation.
    """
    dest = _query_destination(
        destination_id=destination_id,
        workspace_id=workspace_id,
        active_only=False,
    )

    if not dest:
        return [f"Destination {destination_id} not found in this workspace."]
    if not dest.is_active:
        return [f"Destination '{dest.name}' is inactive. Activate it before using in a skill."]
    return []
