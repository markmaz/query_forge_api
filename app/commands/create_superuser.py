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
import pyotp
from flask.cli import with_appcontext
from werkzeug.security import generate_password_hash

from app.services.auth.totp_service import TOTP_ISSUER_NAME
from app.services.password_service import generate_otp_secret


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
    from app.models.rbac import Role
    from app.services.rbac_service import ensure_system_roles, invalidate_user_roles
    from sqlalchemy import text

    ensure_system_roles()

    # ---------------------------------------------------------------------------
    # Find or create user (raw SQL — users table is not an ORM model)
    # ---------------------------------------------------------------------------

    row = db.session.execute(
        text(
            """
            SELECT user_id, username, otp_secret, otp_totp_secret, otp_totp_enabled
            FROM users
            WHERE email = :email
            LIMIT 1
            """
        ),
        {"email": email},
    ).fetchone()

    totp_secret: str | None = None
    totp_uri: str | None = None

    if row:
        user_id = row[0]
        existing_username = str(row[1] or "").strip()
        existing_otp_secret = str(row[2] or "").strip()
        existing_totp_secret = str(row[3] or "").strip()
        existing_totp_enabled = bool(row[4])
        click.echo(
            click.style(f"User {email!r} already exists (user_id={user_id}).", fg="yellow")
        )
        update_fields: list[str] = []
        params = {"user_id": user_id}
        if not existing_username:
            update_fields.append("username = :username")
            params["username"] = email.split("@")[0]
        if not existing_otp_secret:
            update_fields.append("otp_secret = :otp_secret")
            params["otp_secret"] = generate_otp_secret()
        if not existing_totp_secret:
            totp_secret = pyotp.random_base32()
            update_fields.extend(
                [
                    "otp_totp_secret = :otp_totp_secret",
                    "otp_totp_enabled = 1",
                    "otp_totp_confirmed_at = UTC_TIMESTAMP()",
                    "otp_mfa_method = 'totp'",
                    "two_factor_preference = 'Authenticator'",
                ]
            )
            params["otp_totp_secret"] = totp_secret
        elif not existing_totp_enabled:
            totp_secret = existing_totp_secret
            update_fields.extend(
                [
                    "otp_totp_enabled = 1",
                    "otp_totp_confirmed_at = UTC_TIMESTAMP()",
                    "otp_mfa_method = 'totp'",
                    "two_factor_preference = 'Authenticator'",
                ]
            )
        if update_fields:
            db.session.execute(
                text(
                    f"UPDATE users SET {', '.join(update_fields)} WHERE user_id = :user_id"
                ),
                params,
            )
            db.session.commit()
            click.echo(
                click.style(
                    f"Backfilled {' and '.join(field.split(' = ', 1)[0] for field in update_fields)} for {email!r}.",
                    fg="green",
                )
            )
        if totp_secret:
            totp_uri = pyotp.TOTP(totp_secret).provisioning_uri(name=email, issuer_name=TOTP_ISSUER_NAME)
    else:
        user_id = str(uuid.uuid4())
        password_hash = generate_password_hash(password)
        totp_secret = pyotp.random_base32()
        db.session.execute(
            text(
                "INSERT INTO users ("
                "user_id, username, password, email, otp_secret, "
                "otp_totp_secret, otp_totp_enabled, otp_totp_confirmed_at, otp_mfa_method, two_factor_preference, status"
                ") VALUES ("
                ":user_id, :username, :password, :email, :otp_secret, "
                ":otp_totp_secret, 1, UTC_TIMESTAMP(), 'totp', 'Authenticator', '1'"
                ")"
            ),
            {
                "user_id": user_id,
                "username": email.split("@")[0],
                "password": password_hash,
                "email": email,
                "otp_secret": generate_otp_secret(),
                "otp_totp_secret": totp_secret,
            },
        )
        db.session.commit()
        totp_uri = pyotp.TOTP(totp_secret).provisioning_uri(name=email, issuer_name=TOTP_ISSUER_NAME)
        click.echo(click.style(f"Created user {email!r} (user_id={user_id}).", fg="green"))

    # ---------------------------------------------------------------------------
    # Assign super_admin role if not already assigned
    # ---------------------------------------------------------------------------

    super_admin_role = Role.get_by_name("super_admin")
    if not super_admin_role:
        click.echo(
            click.style(
                "Error: 'super_admin' role not found after RBAC seed.",
                fg="red",
            )
        )
        sys.exit(1)

    existing_ur = db.session.execute(
        text(
            """
            SELECT id
            FROM user_roles
            WHERE user_id = :user_id
              AND role_id = :role_id
              AND workspace_id IS NULL
            LIMIT 1
            """
        ),
        {
            "user_id": user_id,
            "role_id": super_admin_role.id,
        },
    ).fetchone()

    if existing_ur:
        click.echo(
            click.style(f"User {email!r} already has super_admin role.", fg="yellow")
        )
    else:
        db.session.execute(
            text(
                """
                INSERT INTO user_roles (user_id, workspace_id, role_id, granted_by)
                VALUES (:user_id, NULL, :role_id, :granted_by)
                """
            ),
            {
                "user_id": user_id,
                "role_id": super_admin_role.id,
                "granted_by": user_id,
            },
        )
        db.session.commit()
        invalidate_user_roles(user_id)
        click.echo(click.style(f"Assigned super_admin role to {email!r}.", fg="green"))

    if totp_secret:
        click.echo(click.style("Bootstrap TOTP configured.", fg="green"))
        click.echo(f"TOTP secret: {totp_secret}")
        click.echo(f"TOTP URI: {totp_uri}")

    click.echo(click.style("Done.", fg="green", bold=True))
