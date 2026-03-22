"""
app/commands/seed_rbac_roles.py

Flask CLI command to seed the canonical RBAC role catalog.

Usage:
    flask seed-rbac-roles
"""

from __future__ import annotations

import click
from flask.cli import with_appcontext


@click.command("seed-rbac-roles")
@with_appcontext
def seed_rbac_roles_command():
    """Ensure the canonical RBAC role catalog exists."""
    from app.services.rbac_service import ensure_system_roles

    created = ensure_system_roles()
    if created:
        click.echo(f"Seeded {len(created)} RBAC role(s).")
        return
    click.echo("RBAC roles already seeded.")
