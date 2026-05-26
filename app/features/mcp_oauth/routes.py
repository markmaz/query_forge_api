from __future__ import annotations

from urllib.parse import urlparse

from flask import Flask, jsonify, make_response, redirect, render_template_string, request
from flask_restx import Namespace, Resource, fields

from app.api_config import NAME, VERSION, build_url
from app.exceptions.forge_error import ForgeError
from app.services.mcp_oauth import AuthorizationCodeService, DynamicClientRegistrationService, OAuthTokenService

from . import app_principal_api
from .metadata import authorization_server_metadata

mcp_oauth_ns = Namespace(
    "mcp-oauth",
    description=(
        "OAuth discovery endpoints for the QueryForge MCP authorization wrapper. "
        "These endpoints describe how remote MCP clients discover QueryForge OAuth "
        "authorization, token, registration, and revocation capabilities."
    ),
)
oauth_ns = Namespace(
    "oauth",
    description=(
        "Protocol OAuth endpoints for remote QueryForge MCP clients. "
        "This surface implements dynamic client registration, authorization-code + PKCE, "
        "token exchange, refresh rotation, and refresh-token revocation for MCP access."
    ),
)


def _csp_origin(url: str) -> str:
    parsed = urlparse(str(url or ""))
    if not parsed.scheme or not parsed.netloc:
        return "'self'"
    return f"{parsed.scheme}://{parsed.netloc}"


_AUTHORIZE_TEMPLATE = """
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Authorize QueryForge MCP Access</title>
    <style>
      :root {
        --ink: #14201d;
        --muted: #6b7280;
        --line: #e5e7eb;
        --paper: #ffffff;
        --field: #fbfcfe;
        --qf-primary: #2b5f60;
        --qf-secondary: #c06240;
        --qf-orange: #ff4d1f;
        --qf-orange-600: #e6451c;
        --qf-sidebar: #0b0f17;
        --qf-sidebar-2: #0f172a;
        --qf-canvas: #f6f8fb;
        --danger: #7f1d1d;
      }

      * { box-sizing: border-box; }

      body {
        min-height: 100vh;
        margin: 0;
        color: var(--ink);
        font-family: ui-sans-serif, "Aptos", "Segoe UI", system-ui, sans-serif;
        background:
          radial-gradient(circle at 12% 16%, rgba(43, 95, 96, 0.18), transparent 28rem),
          radial-gradient(circle at 84% 18%, rgba(255, 77, 31, 0.16), transparent 26rem),
          linear-gradient(135deg, #f6f8fb 0%, #eef3f5 52%, #fff7f2 100%);
      }

      body::before {
        position: fixed;
        inset: 0;
        z-index: -1;
        content: "";
        opacity: 0.16;
        background-image:
          linear-gradient(rgba(15, 23, 42, 0.10) 1px, transparent 1px),
          linear-gradient(90deg, rgba(15, 23, 42, 0.10) 1px, transparent 1px);
        background-size: 42px 42px;
      }

      main {
        display: grid;
        min-height: 100vh;
        place-items: center;
        padding: 40px 18px;
      }

      .shell {
        display: grid;
        grid-template-columns: minmax(0, 0.92fr) minmax(360px, 1.08fr);
        width: min(980px, 100%);
        overflow: hidden;
        border: 1px solid rgba(15, 23, 42, 0.12);
        border-radius: 28px;
        background: rgba(255, 255, 255, 0.9);
        box-shadow: 0 34px 90px rgba(15, 23, 42, 0.18);
        backdrop-filter: blur(18px);
      }

      .summary {
        position: relative;
        display: flex;
        min-height: 620px;
        flex-direction: column;
        justify-content: space-between;
        padding: 34px;
        color: #eef6ea;
        background:
          linear-gradient(160deg, rgba(11, 15, 23, 0.98), rgba(15, 23, 42, 0.96)),
          radial-gradient(circle at 26% 16%, rgba(43, 95, 96, 0.55), transparent 18rem),
          radial-gradient(circle at 80% 82%, rgba(192, 98, 64, 0.32), transparent 16rem);
      }

      .summary::after {
        position: absolute;
        right: -70px;
        bottom: -90px;
        width: 260px;
        height: 260px;
        border: 1px solid rgba(255, 77, 31, 0.26);
        border-radius: 50%;
        content: "";
      }

      .brand {
        display: flex;
        align-items: center;
        gap: 12px;
        font-weight: 800;
        letter-spacing: 0.02em;
      }

      .mark {
        display: block;
        width: 42px;
        height: 42px;
        border-radius: 14px;
        object-fit: cover;
        object-position: center;
        background: rgba(255, 255, 255, 0.06);
        box-shadow: 0 10px 26px rgba(255, 77, 31, 0.16);
      }

      .eyebrow {
        width: fit-content;
        margin: 52px 0 14px;
        border: 1px solid rgba(255, 77, 31, 0.34);
        border-radius: 999px;
        padding: 8px 12px;
        color: #ffd2c2;
        font-size: 12px;
        font-weight: 750;
        letter-spacing: 0.08em;
        text-transform: uppercase;
      }

      h1 {
        margin: 0;
        max-width: 11ch;
        font-family: ui-serif, Georgia, "Times New Roman", serif;
        font-size: clamp(40px, 5vw, 68px);
        line-height: 0.92;
        letter-spacing: -0.045em;
      }

      .summary-copy {
        max-width: 34rem;
        margin: 24px 0 0;
        color: rgba(255, 255, 255, 0.78);
        font-size: 17px;
        line-height: 1.6;
      }

      .resource-card {
        position: relative;
        z-index: 1;
        margin-top: 34px;
        border: 1px solid rgba(255, 77, 31, 0.22);
        border-radius: 20px;
        padding: 18px;
        background: rgba(255, 255, 255, 0.08);
      }

      .resource-label {
        display: block;
        color: rgba(255, 255, 255, 0.58);
        font-size: 12px;
        font-weight: 800;
        letter-spacing: 0.08em;
        text-transform: uppercase;
      }

      code {
        display: block;
        margin-top: 8px;
        overflow-wrap: anywhere;
        color: #ffd2c2;
        font-family: "SFMono-Regular", Consolas, "Liberation Mono", monospace;
        font-size: 13px;
      }

      .panel {
        padding: 38px;
      }

      .client-line {
        margin: 0 0 8px;
        color: var(--muted);
        font-size: 14px;
        font-weight: 700;
        letter-spacing: 0.03em;
        text-transform: uppercase;
      }

      h2 {
        margin: 0;
        font-family: ui-serif, Georgia, "Times New Roman", serif;
        font-size: clamp(30px, 4vw, 42px);
        line-height: 1.05;
        letter-spacing: -0.035em;
      }

      .lead {
        margin: 14px 0 24px;
        color: var(--muted);
        font-size: 15px;
        line-height: 1.65;
      }

      .scopes {
        margin: 0 0 26px;
        border: 1px solid var(--line);
        border-radius: 18px;
        padding: 16px;
        background: #fbfcfe;
      }

      .scopes strong {
        display: block;
        margin-bottom: 12px;
        font-size: 13px;
        letter-spacing: 0.04em;
        text-transform: uppercase;
      }

      .scope-list {
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
        margin: 0;
        padding: 0;
        list-style: none;
      }

      .scope-list li {
        border: 1px solid #cfd8c4;
        border-radius: 999px;
        padding: 7px 10px;
        color: var(--qf-primary);
        background: #ffffff;
        font-size: 12px;
        font-weight: 750;
      }

      label {
        display: block;
        margin-top: 16px;
        color: #111827;
        font-size: 13px;
        font-weight: 800;
      }

      input {
        width: 100%;
        margin-top: 7px;
        border: 1px solid #cfd6cb;
        border-radius: 14px;
        padding: 13px 14px;
        color: var(--ink);
        background: var(--field);
        box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.65);
        font: inherit;
        outline: none;
        transition: border-color 150ms ease, box-shadow 150ms ease, background 150ms ease;
      }

      input:focus {
        border-color: var(--qf-primary);
        background: #ffffff;
        box-shadow: 0 0 0 4px rgba(43, 95, 96, 0.18);
      }

      .actions {
        display: grid;
        gap: 12px;
        margin-top: 26px;
      }

      button {
        width: 100%;
        border: 0;
        border-radius: 16px;
        padding: 14px 18px;
        color: white;
        background: linear-gradient(135deg, var(--qf-orange), var(--qf-orange-600));
        box-shadow: 0 14px 30px rgba(255, 77, 31, 0.24);
        font: inherit;
        font-weight: 850;
        cursor: pointer;
      }

      button:hover { filter: brightness(1.05); }

      .note {
        margin: 0;
        color: var(--muted);
        font-size: 13px;
        line-height: 1.5;
      }

      .security-note {
        margin-top: 20px;
        border-left: 3px solid var(--qf-secondary);
        padding: 2px 0 2px 12px;
        color: #6b4c40;
        font-size: 13px;
        line-height: 1.5;
      }

      @media (max-width: 820px) {
        main { align-items: start; padding: 18px; }
        .shell { grid-template-columns: 1fr; border-radius: 22px; }
        .summary { min-height: auto; padding: 28px; }
        .eyebrow { margin-top: 34px; }
        h1 { max-width: none; }
        .panel { padding: 28px; }
      }
    </style>
  </head>
  <body>
    <main>
      <section class="shell" aria-label="Authorize QueryForge MCP access">
        <div class="summary">
          <div>
            <div class="brand">
              <img class="mark" src="/static/images/qf_logo_mark.png" alt="QueryForge logo">
              <span>QueryForge</span>
            </div>
            <div class="eyebrow">MCP authorization</div>
            <h1>Connect governed context.</h1>
            <p class="summary-copy">
              Authorize this MCP client to use QueryForge's governed semantic layer.
              The client can only access workspaces and previews already allowed by your QueryForge permissions.
            </p>
          </div>
          <div class="resource-card">
            <span class="resource-label">Requested resource</span>
            <code>{{ resource }}</code>
          </div>
        </div>
        <div class="panel">
          <p class="client-line">{{ client_name }} is requesting access</p>
          <h2>Sign in to approve access</h2>
          <p class="lead">
            Use your QueryForge credentials to create a short-lived MCP authorization.
            This does not grant new roles, workspace access, or database permissions.
          </p>
          <div class="scopes">
            <strong>Requested scopes</strong>
            <ul class="scope-list">{% for scope in scopes %}<li>{{ scope }}</li>{% endfor %}</ul>
          </div>
          <form method="post" action="/oauth/authorize">
            {% for key, value in hidden_fields.items() %}
              <input type="hidden" name="{{ key }}" value="{{ value }}">
            {% endfor %}
            <label>Username or email
              <input name="username" autocomplete="username" placeholder="you@example.com" required>
            </label>
            <label>Password
              <input name="password" type="password" autocomplete="current-password" placeholder="Enter your password" required>
            </label>
            <label>TOTP code <span class="note">optional unless enabled</span>
              <input name="totp_code" inputmode="numeric" autocomplete="one-time-code" placeholder="123456">
            </label>
            <div class="actions">
              <button type="submit" name="consent" value="approve">Allow MCP access</button>
              <p class="note">You can revoke this authorization later. Preview tools still require QueryForge preview access.</p>
            </div>
          </form>
          <p class="security-note">
            Only approve clients you started. If this page opened unexpectedly, close it and review active MCP clients.
          </p>
        </div>
      </section>
    </main>
  </body>
</html>
"""

_metadata_model = mcp_oauth_ns.model(
    "MCPOAuthAuthorizationServerMetadata",
    {
        "issuer": fields.String(
            required=True,
            description="Canonical issuer URL for QueryForge OAuth tokens, without a trailing slash.",
            example="https://api.query-forge.com",
        ),
        "authorization_endpoint": fields.String(
            required=True,
            description="Authorization-code + PKCE start endpoint for human MCP authorization.",
            example="https://api.query-forge.com/oauth/authorize",
        ),
        "token_endpoint": fields.String(
            required=True,
            description="Token exchange endpoint for authorization-code, refresh-token, and app-client grants.",
            example="https://api.query-forge.com/oauth/token",
        ),
        "registration_endpoint": fields.String(
            required=False,
            description="Dynamic client registration endpoint when dynamic registration is enabled.",
            example="https://api.query-forge.com/oauth/register",
        ),
        "revocation_endpoint": fields.String(
            required=True,
            description="Endpoint for revoking OAuth refresh/access token identifiers and MCP consent sessions.",
            example="https://api.query-forge.com/oauth/revoke",
        ),
        "response_types_supported": fields.List(
            fields.String,
            required=True,
            description="OAuth response types supported by QueryForge MCP OAuth. Phase 2 exposes code only.",
            example=["code"],
        ),
        "grant_types_supported": fields.List(
            fields.String,
            required=True,
            description="OAuth grant types supported by the advertised authorization server.",
            example=["authorization_code", "refresh_token", "client_credentials"],
        ),
        "code_challenge_methods_supported": fields.List(
            fields.String,
            required=True,
            description="PKCE code challenge methods accepted by the authorization endpoint.",
            example=["S256"],
        ),
        "scopes_supported": fields.List(
            fields.String,
            required=True,
            description="MCP channel scopes clients may request.",
            example=["qf:mcp:read", "qf:mcp:plan", "qf:mcp:preview"],
        ),
        "token_endpoint_auth_methods_supported": fields.List(
            fields.String,
            required=True,
            description="Client authentication methods supported by the token endpoint.",
            example=["none", "client_secret_basic", "client_secret_post"],
        ),
        "service_documentation": fields.String(
            required=True,
            description="Operational documentation URL for QueryForge MCP OAuth behavior.",
            example="https://api.query-forge.com/docs/mcp",
        ),
    },
)

_registration_request_model = oauth_ns.model(
    "OAuthDynamicClientRegistrationRequest",
    {
        "redirect_uris": fields.List(
            fields.String,
            required=True,
            description=(
                "Absolute HTTPS redirect URIs supplied by the remote MCP client. "
                "Every URI host must match `OAUTH_ALLOWED_REDIRECT_HOSTS`."
            ),
            example=["https://chatgpt.com/aip/g-queryforge/oauth/callback"],
        ),
        "client_name": fields.String(
            required=False,
            description="Human-readable client name shown in consent and admin review screens.",
            example="ChatGPT QueryForge Connector",
        ),
        "grant_types": fields.List(
            fields.String,
            required=False,
            description=(
                "Requested OAuth grant types. Supported values are `authorization_code`, "
                "`refresh_token` when enabled, and `client_credentials` for future app-principal auth."
            ),
            example=["authorization_code", "refresh_token"],
        ),
        "response_types": fields.List(
            fields.String,
            required=False,
            description="Requested OAuth response types. QueryForge MCP OAuth supports `code` only.",
            example=["code"],
        ),
        "scope": fields.String(
            required=False,
            description="Space-delimited MCP scopes requested by the client.",
            example="qf:mcp:read qf:mcp:plan qf:mcp:preview",
        ),
        "token_endpoint_auth_method": fields.String(
            required=False,
            description=(
                "Client authentication method for token exchange. Use `none` for public PKCE clients; "
                "`client_secret_basic` and `client_secret_post` issue a client secret."
            ),
            example="none",
        ),
        "client_uri": fields.String(
            required=False,
            description="Optional absolute URL describing the OAuth client.",
            example="https://chatgpt.com",
        ),
        "logo_uri": fields.String(
            required=False,
            description="Optional absolute URL for the OAuth client's logo.",
            example="https://chatgpt.com/logo.png",
        ),
        "contacts": fields.List(
            fields.String,
            required=False,
            description="Optional operator contact addresses supplied by the registering client.",
            example=["admin@example.com"],
        ),
    },
)

_registration_response_model = oauth_ns.model(
    "OAuthDynamicClientRegistrationResponse",
    {
        "client_id": fields.String(required=True, description="Issued OAuth client identifier."),
        "client_secret": fields.String(
            required=False,
            description="Issued client secret. Present only for confidential token endpoint auth methods.",
        ),
        "client_secret_expires_at": fields.Integer(
            required=False,
            description="Client secret expiry epoch seconds. `0` means no independent secret expiry.",
            example=0,
        ),
        "client_id_issued_at": fields.Integer(
            required=True,
            description="Client registration issue time as epoch seconds.",
            example=1777000000,
        ),
        "redirect_uris": fields.List(fields.String, required=True),
        "grant_types": fields.List(fields.String, required=True),
        "response_types": fields.List(fields.String, required=True),
        "scope": fields.String(required=True),
        "token_endpoint_auth_method": fields.String(required=True),
        "client_name": fields.String(required=False),
        "client_uri": fields.String(required=False),
        "logo_uri": fields.String(required=False),
        "contacts": fields.List(fields.String, required=False),
    },
)

_token_request_model = oauth_ns.model(
    "OAuthTokenRequest",
    {
        "grant_type": fields.String(
            required=True,
            description="OAuth grant type. Supported values are `authorization_code` and `refresh_token`.",
            example="authorization_code",
        ),
        "client_id": fields.String(
            required=True,
            description="Dynamic OAuth client id issued by `/oauth/register`.",
            example="qf_mcp_example",
        ),
        "client_secret": fields.String(
            required=False,
            description=(
                "Client secret for confidential clients using `client_secret_post`. "
                "Public PKCE clients registered with `token_endpoint_auth_method=none` omit this field."
            ),
        ),
        "code": fields.String(
            required=False,
            description="Authorization code returned by `/oauth/authorize`; required for `authorization_code`.",
        ),
        "redirect_uri": fields.String(
            required=False,
            description="Redirect URI used in the authorization request; must match the stored authorization code.",
            example="https://chatgpt.com/aip/g-queryforge/oauth/callback",
        ),
        "resource": fields.String(
            required=False,
            description="MCP resource URL. When present, it must match the authorization code and `MCP_RESOURCE_URL`.",
            example="https://mcp.query-forge.com",
        ),
        "code_verifier": fields.String(
            required=False,
            description="PKCE verifier corresponding to the authorization request `code_challenge`.",
        ),
        "refresh_token": fields.String(
            required=False,
            description="Opaque persisted refresh token; required for `refresh_token` grant rotation.",
        ),
    },
)

_token_response_model = oauth_ns.model(
    "OAuthTokenResponse",
    {
        "access_token": fields.String(
            required=True,
            description="JWT access token scoped to QueryForge MCP only (`typ=mcp_access`, `aud=MCP_RESOURCE_URL`).",
        ),
        "token_type": fields.String(required=True, description="Always `Bearer`.", example="Bearer"),
        "expires_in": fields.Integer(
            required=True,
            description="Access-token lifetime in seconds from `OAUTH_ACCESS_TOKEN_TTL_SECONDS`.",
            example=3600,
        ),
        "scope": fields.String(
            required=True,
            description="Space-delimited MCP scopes authorized for this token.",
            example="qf:mcp:read qf:mcp:plan",
        ),
        "refresh_token": fields.String(
            required=False,
            description=(
                "Opaque refresh token when `OAUTH_ENABLE_REFRESH_TOKENS=true` and the client registration "
                "allows the refresh-token grant. Refresh tokens are rotated on every use."
            ),
        ),
    },
)

_revocation_request_model = oauth_ns.model(
    "OAuthTokenRevocationRequest",
    {
        "token": fields.String(
            required=True,
            description="Refresh token to revoke. Unknown tokens are accepted idempotently.",
        ),
        "token_type_hint": fields.String(
            required=False,
            description=(
                "Optional OAuth token type hint. `refresh_token` is durably revoked. Access-token revocation "
                "is accepted as a no-op in v1 because access tokens are short-lived JWTs."
            ),
            example="refresh_token",
        ),
    },
)

_revocation_response_model = oauth_ns.model(
    "OAuthTokenRevocationResponse",
    {
        "revoked": fields.Boolean(
            required=True,
            description="Always true for syntactically valid revocation requests, per OAuth revocation idempotency.",
            example=True,
        ),
    },
)


def _oauth_request_payload() -> dict[str, str]:
    payload = request.form.to_dict(flat=True) if request.form else (request.get_json(silent=True) or {})
    normalized = {str(key): str(value) for key, value in dict(payload).items() if value is not None}
    auth = request.authorization
    if auth and auth.username:
        normalized.setdefault("client_id", str(auth.username))
        normalized.setdefault("client_secret", str(auth.password or ""))
    return normalized


@mcp_oauth_ns.route("/authorization-server-metadata")
class MCPOAuthAuthorizationServerMetadata(Resource):
    @mcp_oauth_ns.doc(
        summary="Return QueryForge MCP OAuth authorization-server metadata",
        description=(
            "Returns the same standards-shaped authorization-server discovery payload served "
            "from `/.well-known/oauth-authorization-server`. This documented API route exists "
            "so Swagger consumers can inspect the MCP OAuth discovery contract, while MCP and "
            "OAuth clients should use the well-known endpoint for protocol discovery."
        ),
        responses={
            200: (
                "Authorization-server metadata describing issuer, authorization, token, "
                "registration, revocation, PKCE, grant type, and MCP scope support."
            )
        },
    )
    @mcp_oauth_ns.marshal_with(_metadata_model, code=200)
    def get(self):
        return authorization_server_metadata(), 200


@oauth_ns.route("/register")
class OAuthDynamicClientRegistration(Resource):
    @oauth_ns.doc(
        summary="Register a remote MCP OAuth client",
        description=(
            "Creates a dynamic OAuth client registration for a remote MCP client such as ChatGPT. "
            "The endpoint is intentionally unauthenticated because dynamic registration happens before "
            "the user authorization flow. QueryForge still restricts registration by redirect URI host "
            "allowlist, supported grant types, supported scopes, and token endpoint auth method. "
            "Expired dynamic clients are cleaned opportunistically before a new registration is stored."
        ),
        responses={
            201: "Client registration created and persisted.",
            400: "Invalid redirect URI, scope, grant type, response type, or client metadata.",
            404: "Dynamic client registration is disabled by configuration.",
            500: "Unexpected persistence or registration failure.",
        },
    )
    @oauth_ns.expect(_registration_request_model, validate=False)
    @oauth_ns.response(201, "Client registration created and persisted.", _registration_response_model)
    def post(self):
        try:
            payload = request.get_json(silent=True) or {}
            return DynamicClientRegistrationService().register_client(payload), 201
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code


@oauth_ns.route("/authorize")
class OAuthAuthorize(Resource):
    @oauth_ns.doc(
        summary="Start or complete MCP OAuth authorization-code flow",
        description=(
            "GET validates the OAuth authorization request and renders a backend-hosted QueryForge "
            "login/consent form. POST validates the same request parameters plus user credentials, "
            "checks TOTP when enabled for the user, records a short-lived PKCE-bound authorization "
            "code, and redirects back to the registered client redirect URI with `code`, `state`, "
            "and `resource`. Token exchange is implemented separately by `/oauth/token`."
        ),
        params={
            "response_type": "Must be `code`.",
            "client_id": "Dynamic OAuth client id issued by `/oauth/register`.",
            "redirect_uri": "Registered HTTPS redirect URI for the client.",
            "resource": "MCP resource URL; must match `MCP_RESOURCE_URL`.",
            "scope": "Space-delimited MCP scopes.",
            "state": "Opaque client state echoed to the redirect URI.",
            "code_challenge": "PKCE verifier challenge.",
            "code_challenge_method": "PKCE challenge method, normally `S256`.",
        },
        responses={
            200: "HTML QueryForge login/consent form.",
            302: "Authorization code redirect after successful POST.",
            400: "Invalid OAuth request, PKCE fields, redirect URI, resource, or consent.",
            401: "Invalid credentials or TOTP failure.",
        },
    )
    def get(self):
        try:
            payload = request.args.to_dict(flat=True)
            ctx = AuthorizationCodeService().validate_authorization_request(payload)
            hidden_fields = {
                key: str(payload.get(key) or "")
                for key in (
                    "response_type",
                    "client_id",
                    "redirect_uri",
                    "resource",
                    "scope",
                    "state",
                    "code_challenge",
                    "code_challenge_method",
                    "nonce",
                )
                if str(payload.get(key) or "").strip()
            }
            html = render_template_string(
                _AUTHORIZE_TEMPLATE,
                client_name=ctx.client_name or ctx.client_id,
                resource=ctx.resource,
                scopes=ctx.scopes,
                hidden_fields=hidden_fields,
            )
            response = make_response(html, 200)
            response.headers["Content-Type"] = "text/html; charset=utf-8"
            response.headers["Content-Security-Policy"] = (
                "default-src 'none'; "
                "img-src 'self'; "
                "style-src 'unsafe-inline'; "
                f"form-action 'self' {_csp_origin(ctx.redirect_uri)}; "
                "base-uri 'none'; "
                "frame-ancestors 'none'"
            )
            return response
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code

    @oauth_ns.expect(oauth_ns.model("OAuthAuthorizeFormPost", {}), validate=False)
    def post(self):
        try:
            payload = request.form.to_dict(flat=True) or (request.get_json(silent=True) or {})
            redirect_url = AuthorizationCodeService().authorize_with_password(payload)
            return redirect(redirect_url, code=302)
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code


@oauth_ns.route("/token")
class OAuthToken(Resource):
    @oauth_ns.doc(
        summary="Exchange MCP OAuth grants for MCP access tokens",
        description=(
            "Exchanges a one-time authorization code and PKCE verifier for a QueryForge MCP access token. "
            "The issued JWT is intentionally audience-bound to `MCP_RESOURCE_URL` and uses `typ=mcp_access`, "
            "so it cannot be reused as a normal QueryForge API login token. When refresh tokens are enabled "
            "and the registered client allows the refresh-token grant, the response includes an opaque refresh "
            "token. Refresh-token requests rotate the persisted refresh token on every successful use."
        ),
        responses={
            200: "Access token issued. Refresh token included only when enabled and allowed.",
            400: "Invalid grant type, missing PKCE verifier, invalid authorization code, resource mismatch, or grant not allowed.",
            401: "Unknown client, invalid confidential client secret, invalid refresh token, or refresh replay.",
        },
    )
    @oauth_ns.expect(_token_request_model, validate=False)
    @oauth_ns.marshal_with(_token_response_model, code=200)
    def post(self):
        try:
            return OAuthTokenService().issue_token(_oauth_request_payload()), 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code


@oauth_ns.route("/revoke")
class OAuthRevoke(Resource):
    @oauth_ns.doc(
        summary="Revoke a persisted MCP OAuth refresh token",
        description=(
            "Revokes an opaque MCP OAuth refresh token by hash. The endpoint follows OAuth revocation "
            "idempotency: unknown tokens still return success so clients cannot use the endpoint as a token "
            "oracle. QueryForge MCP access tokens are short-lived JWTs; v1 accepts access-token revocation "
            "requests but durable revocation is enforced for refresh tokens."
        ),
        responses={
            200: "Token revocation accepted.",
            400: "Missing token value.",
        },
    )
    @oauth_ns.expect(_revocation_request_model, validate=False)
    @oauth_ns.marshal_with(_revocation_response_model, code=200)
    def post(self):
        try:
            return OAuthTokenService().revoke_token(_oauth_request_payload()), 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code


def register(api):
    api.add_namespace(mcp_oauth_ns, path=build_url("/", NAME, VERSION, "mcp-oauth"))
    api.add_namespace(oauth_ns, path="/oauth")
    app_principal_api.register(api)


def register_well_known_routes(app: Flask) -> None:
    @app.get("/.well-known/oauth-authorization-server")
    def mcp_oauth_authorization_server_metadata():
        return jsonify(authorization_server_metadata())
