from __future__ import annotations

from app.models.mcp_oauth import (
    MCPAppClient,
    MCPOAuthAuditLog,
    MCPPrincipalGrant,
    OAuthAuthorizationCode,
    OAuthClient,
    OAuthConsent,
    OAuthRefreshToken,
    WorkspaceMCPSettings,
)


def test_mcp_oauth_model_table_names_are_stable() -> None:
    assert WorkspaceMCPSettings.__tablename__ == "workspace_mcp_settings"
    assert OAuthClient.__tablename__ == "oauth_clients"
    assert OAuthAuthorizationCode.__tablename__ == "oauth_authorization_codes"
    assert OAuthRefreshToken.__tablename__ == "oauth_refresh_tokens"
    assert MCPPrincipalGrant.__tablename__ == "mcp_principal_grants"
    assert OAuthConsent.__tablename__ == "oauth_consents"
    assert MCPAppClient.__tablename__ == "mcp_app_clients"
    assert MCPOAuthAuditLog.__tablename__ == "mcp_oauth_audit_log"


def test_workspace_mcp_settings_model_captures_workspace_enablement_columns() -> None:
    columns = WorkspaceMCPSettings.__table__.columns

    assert "workspace_id" in columns
    assert "enabled" in columns
    assert "enabled_by" in columns
    assert "disabled_by" in columns
    assert "default_preview_row_limit" in columns
    assert "max_preview_row_limit" in columns
    assert "block_sensitive_domains" in columns


def test_principal_grant_model_supports_user_and_app_authorization_shape() -> None:
    columns = MCPPrincipalGrant.__table__.columns
    indexes = {index.name for index in MCPPrincipalGrant.__table__.indexes}
    unique_constraints = {constraint.name for constraint in MCPPrincipalGrant.__table__.constraints}

    assert "principal_type" in columns
    assert "principal_id" in columns
    assert "workspace_id" in columns
    assert "allowed_tools" in columns
    assert "allowed_domain_keys" in columns
    assert "can_preview" in columns
    assert "preview_row_limit" in columns
    assert "revoked_at" in columns
    assert "idx_mpg_principal_workspace" in indexes
    assert "uidx_mpg_principal_workspace" in unique_constraints


def test_oauth_foundation_models_capture_token_and_audit_lifecycle() -> None:
    assert "code_challenge" in OAuthAuthorizationCode.__table__.columns
    assert "code_challenge_method" in OAuthAuthorizationCode.__table__.columns
    assert "consumed_at" in OAuthAuthorizationCode.__table__.columns
    assert "replaced_by_hash" in OAuthRefreshToken.__table__.columns
    assert "expires_at" in OAuthConsent.__table__.columns
    assert "rotation_required_at" in MCPAppClient.__table__.columns
    assert "decision" in MCPOAuthAuditLog.__table__.columns
    assert "details_json" in MCPOAuthAuditLog.__table__.columns
