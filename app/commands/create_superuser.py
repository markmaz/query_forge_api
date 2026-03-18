"""
app/commands/create_superuser.py

Flask CLI command to create the default superuser in production.

Usage:
    flask create-superuser

Reads credentials from environment variables:
    SUPERUSER_EMAIL          required
    SUPERUSER_PASSWORD       required (plain text — hashed here, never stored)

Safe to re-run — skips if email already exists, re-assigns
super_admin role if missing.

Register in app factory:
    from app.commands.create_superuser import create_superuser_command
    app.cli.add_command(create_superuser_command)

Seam notes:
    users.user_id  — VARCHAR(255) PK (not id)
    users.password — column name (not password_hash)
    users.status   — '0' inactive, '1' active (not is_active bool)
    No first_name / last_name columns in users table
"""

from __future__ import annotations

import os
import sys
import uuid

import click
from flask.cli import with_appcontext
from werkzeug.security import generate_password_hash


@click.command("create-superuser")
@with_appcontext
def create_superuser_command():
    """Create the default superuser from environment variables."""

    email = os.environ.get("SUPERUSER_EMAIL", "").strip()
    password = os.environ.get("SUPERUSER_PASSWORD", "").strip()

    missing = []
    if not email:
        missing.append("SUPERUSER_EMAIL")
    if not password:
        missing.append("SUPERUSER_PASSWORD")
    if missing:
        click.echo(
            click.style(
                f"Error: missing required environment variable(s): {', '.join(missing)}",
                fg="red",
            )
        )
        sys.exit(1)

    if "@" not in email or "." not in email.split("@")[-1]:
        click.echo(click.style(f"Error: invalid email address: {email!r}", fg="red"))
        sys.exit(1)

    from app.extensions import db
    from app.models.rbac import Role, UserRole
    from app.services.rbac_service import invalidate_user_roles
    from sqlalchemy import text

    # ---------------------------------------------------------------------------
    # Find or create user (raw SQL — users table is not an ORM model)
    # ---------------------------------------------------------------------------

    with db.session.connection() as conn:
        row = conn.execute(
            text("SELECT user_id FROM users WHERE email = :email LIMIT 1"),
            {"email": email},
        ).fetchone()

    if row:
        user_id = row[0]
        click.echo(
            click.style(f"User {email!r} already exists (user_id={user_id}).", fg="yellow")
        )
    else:
        user_id = str(uuid.uuid4())
        password_hash = generate_password_hash(password)
        with db.session.connection() as conn:
            conn.execute(
                text(
                    "INSERT INTO users (user_id, username, password, email, status) "
                    "VALUES (:user_id, :username, :password, :email, '1')"
                ),
                {
                    "user_id": user_id,
                    "username": email.split("@")[0],
                    "password": password_hash,
                    "email": email,
                },
            )
            conn.execute(text("COMMIT"))
        click.echo(click.style(f"Created user {email!r} (user_id={user_id}).", fg="green"))

    # ---------------------------------------------------------------------------
    # Assign super_admin role if not already assigned
    # ---------------------------------------------------------------------------

    super_admin_role = Role.get_by_name("super_admin")
    if not super_admin_role:
        click.echo(
            click.style(
                "Error: 'super_admin' role not found. Run seeds/roles.sql first.",
                fg="red",
            )
        )
        sys.exit(1)

    existing_ur = UserRole.query.filter_by(
        user_id=user_id,
        role_id=super_admin_role.id,
    ).first()

    if existing_ur:
        click.echo(
            click.style(f"User {email!r} already has super_admin role.", fg="yellow")
        )
    else:
        ur = UserRole(
            user_id=user_id,
            role_id=super_admin_role.id,
            granted_by=user_id,
        )
        db.session.add(ur)
        db.session.commit()
        invalidate_user_roles(user_id)
        click.echo(click.style(f"Assigned super_admin role to {email!r}.", fg="green"))

    click.echo(click.style("Done.", fg="green", bold=True))
