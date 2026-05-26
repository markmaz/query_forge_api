# QueryForge MCP OAuth Wrapper Design

Date: 2026-05-01

## Objective

Add a production-ready OAuth wrapper for the standalone QueryForge MCP server so ChatGPT and other remote MCP clients can authenticate through QueryForge without bypassing existing workspace, RBAC, domain-visibility, and preview-only execution controls.

This design extends the existing MCP implementation:

- MCP server package: `query-forge-api/mcp_server/`
- MCP implementation spec: `docs/plans/queryforge_mcp_codex_implementation_spec.md`
- target MCP host: `https://mcp.query-forge.com/mcp`
- target API/auth host: `https://api.query-forge.com`

## Current State

The MCP server currently runs as a standalone FastMCP process and exposes governed semantic query tools:

- `search_domains`
- `get_domain_profile`
- `search_dictionary`
- `plan_query`
- `validate_query_plan`
- `compile_query`
- `preview_query`
- `list_saved_queries`
- `run_saved_query`

The current MCP auth layer expects a QueryForge bearer token on every non-OPTIONS request and resolves:

- authenticated user
- workspace access
- effective roles
- visible domain keys
- preview permissions

That is sufficient for local/dev or direct API clients that can supply a QueryForge JWT, but it is not enough for ChatGPT remote MCP because ChatGPT expects standards-based OAuth discovery, PKCE, dynamic client registration, and resource-bound bearer tokens.

## External Protocol Requirements

ChatGPT remote MCP integrations require the MCP server and authorization server to support the MCP authorization profile over OAuth 2.1.

Relevant OpenAI docs:

- `https://developers.openai.com/apps-sdk/build/auth`
- `https://developers.openai.com/api/docs/guides/developer-mode`
- `https://developers.openai.com/apps-sdk/deploy/connect-chatgpt`

Protocol requirements to support:

- remote MCP over HTTPS using streaming HTTP/SSE
- protected-resource metadata from the MCP resource server
- OAuth authorization-server metadata from the authorization server
- authorization-code flow with PKCE `S256`
- dynamic client registration
- `resource` parameter echoed through authorization and token exchange
- access tokens bound to the MCP resource audience
- bearer-token verification on every MCP request

## Design Principles

1. OAuth authenticates the channel. QueryForge still authorizes the data.
2. MCP access is a separate channel permission, not a replacement for normal QueryForge RBAC.
3. Human users and app principals should both be first-class concepts.
4. App principals must receive explicit grants and must not inherit broad human/admin roles.
5. ChatGPT must never supply trusted workspace, user, domain, or role visibility.
6. Tokens minted for MCP must not be reusable as normal QueryForge browser/API tokens.
7. Every MCP call must be auditable by principal, workspace, tool, domain, and decision.

## Target Architecture

```text
ChatGPT
  -> https://mcp.query-forge.com/.well-known/oauth-protected-resource
  -> https://api.query-forge.com/.well-known/oauth-authorization-server
  -> https://api.query-forge.com/oauth/register
  -> https://api.query-forge.com/oauth/authorize
  -> QueryForge login/MFA/consent
  -> https://api.query-forge.com/oauth/token
  -> https://mcp.query-forge.com/mcp with Authorization: Bearer <mcp_access_token>
```

Runtime layers:

```text
ChatGPT remote MCP client
  -> Nginx mcp.query-forge.com
  -> standalone FastMCP resource server
  -> MCP token verifier
  -> QueryForge context resolver
  -> existing QueryForge services
```

Authorization-server layers:

```text
Browser/OAuth redirect
  -> Nginx api.query-forge.com
  -> Flask app/features/mcp_oauth
  -> AuthService / MFA / user services
  -> OAuth client/code/token storage
```

## Principal Model

Use a generic principal model internally so MCP can support both human users and app integrations.

Principal fields:

- `principal_type`: `user` or `app`
- `principal_id`: QueryForge `user_id` or MCP app client id
- `workspace_id`
- `enabled`
- `allowed_tools`
- `allowed_domain_keys`
- `can_preview`
- `preview_row_limit`
- `expires_at`
- `revoked_at`
- the principal grant only applies after the workspace has MCP enabled

Human user principal:

- authenticated through OAuth authorization-code + PKCE
- `principal_type=user`
- `principal_id=<queryforge user_id>`
- permissions are evaluated from current QueryForge workspace/RBAC/domain visibility plus workspace MCP enablement and MCP channel grants
- human MCP channel access is granted by QueryForge RBAC roles, not by required rows in `mcp_principal_grants`

App principal:

- authenticated through an app credential/token exchange flow in v1
- `principal_type=app`
- `principal_id=<mcp_app_client_id>`
- permissions come from explicit app grants only
- app principals do not inherit human roles
- app MCP access is controlled by `mcp_principal_grants`, including workspace, domain, tool, preview, row-limit, expiration, and revocation constraints

## MCP Channel Roles and Capabilities

Add MCP-specific capabilities as workspace-scoped gates.

Recommended names:

- `queryforge_mcp:user`
- `queryforge_mcp:preview`
- `queryforge_mcp:admin`

Behavior:

- `queryforge_mcp:user` allows the principal to use read/planning/compile MCP tools.
- `queryforge_mcp:preview` allows preview-only result tools when existing QueryForge preview permissions also pass.
- `queryforge_mcp:admin` is reserved for future MCP grant/client administration and should not be required for v1 end-user access.

Important decision:

- `workspace_admin` and `super_admin` should not bypass MCP channel grants by default.
- External-AI access is a separate risk surface and should be explicitly enabled.
- production rollout should be default-deny: MCP has a global kill switch and is disabled for each workspace until a workspace admin or higher explicitly enables it.

## Workspace MCP Enablement

MCP availability is workspace-specific.

Authorization model:

- `MCP_ENABLED` is the global runtime kill switch.
- Workspace-level MCP enablement controls whether any principal can use MCP for that workspace.
- A workspace admin or higher can enable/disable MCP for their workspace.
- After MCP is enabled for the workspace, a workspace admin or higher can grant specific users MCP roles for that workspace.
- App principals require explicit workspace-scoped grants.
- Disabling MCP for a workspace immediately denies all human and app MCP access for that workspace, regardless of existing user roles, app grants, OAuth consent, or refresh tokens.

Human workspace flow:

```text
workspace admin enables MCP for workspace
  -> workspace admin grants queryforge_mcp:user to selected users
  -> workspace admin optionally grants queryforge_mcp:preview
  -> user connects ChatGPT through OAuth
  -> MCP calls are authorized only within that workspace and existing QueryForge access
```

App workspace flow:

```text
workspace admin enables MCP for workspace
  -> workspace admin creates app principal
  -> workspace admin grants app allowed tools/domains/preview limits
  -> app obtains MCP access token
  -> MCP calls are authorized only within that workspace grant
```

Admin boundary:

- `workspace_admin` and higher can administer MCP enablement and grants for their workspace.
- `workspace_admin` and higher still do not bypass the requirement that MCP is enabled for the workspace.
- `workspace_admin` and higher still do not automatically receive end-user MCP access unless explicitly granted `queryforge_mcp:user` / `queryforge_mcp:preview`.
- Higher/global admins can manage MCP across workspaces according to existing QueryForge admin boundaries.

## Authorization Evaluation

Every MCP request should evaluate:

```text
valid OAuth/MCP token
AND token typ == mcp_access
AND token issuer is trusted
AND token audience matches MCP resource URL
AND token has required scope
AND MCP is globally enabled
AND MCP is enabled for the requested workspace
AND workspace access passes
AND MCP channel role/capability passes
AND requested tool is allowed
AND requested domain is visible/allowed
AND existing QueryForge RBAC/data policies pass
AND execution/output limits pass
```

For human users:

```text
WorkspaceAccessService.assert_workspace_access(user_id, workspace_id)
AND workspace MCP enablement is active
AND get_effective_roles(user_id, workspace_id)
AND effective roles include queryforge_mcp:user for all MCP tools
AND effective roles include queryforge_mcp:preview for preview tools
AND QueryStudioDomainExplorerService.list_domains(workspace_id, user_id)
AND workspace_has_feature(workspace_id, "query_studio") for preview tools
```

For app principals:

```text
app grant enabled
AND workspace MCP enablement is active
AND grant.workspace_id == requested workspace_id
AND requested tool in grant.allowed_tools
AND requested domain in grant.allowed_domain_keys
AND preview allowed by grant.can_preview
AND preview row limit <= grant.preview_row_limit
```

## Scope Model

Use OAuth scopes as coarse external permissions and QueryForge grants/RBAC as the final source of truth.

Recommended v1 scopes:

- `qf:mcp:read`
- `qf:mcp:plan`
- `qf:mcp:preview`

Scope-to-tool mapping:

| Scope | Tools |
| --- | --- |
| `qf:mcp:read` | `search_domains`, `get_domain_profile`, `search_dictionary`, `list_saved_queries`, resources |
| `qf:mcp:plan` | `plan_query`, `validate_query_plan`, `compile_query` |
| `qf:mcp:preview` | `preview_query`, `run_saved_query` |

Do not add write/admin scopes in v1.

Saved query behavior:

- list user-owned saved queries
- list explicitly shared saved queries visible to the user/principal
- never expose workspace-global saved queries unless a role or grant explicitly permits it
- run saved queries through preview-only execution limits

Raw SQL behavior:

- keep `MCP_INCLUDE_RAW_SQL=false` for ChatGPT-facing deployments
- never expose raw SQL to ChatGPT by default, even if raw SQL is enabled for internal MCP tools
- any future internal raw-SQL exposure must be environment-gated and excluded from ChatGPT client registrations

## Token Design

MCP access tokens should be separate from normal QueryForge access tokens.

Recommended JWT claims:

```json
{
  "iss": "https://api.query-forge.com",
  "aud": "https://mcp.query-forge.com",
  "sub": "user_or_app_principal_id",
  "typ": "mcp_access",
  "jti": "opaque-token-id",
  "iat": 1770000000,
  "exp": 1770003600,
  "client_id": "registered-oauth-client-id",
  "principal_type": "user",
  "scope": "qf:mcp:read qf:mcp:plan",
  "resource": "https://mcp.query-forge.com"
}
```

Refresh tokens:

- implement in v1 behind `OAUTH_ENABLE_REFRESH_TOKENS`
- store only hashed refresh tokens
- rotate refresh tokens on use
- support admin/user revocation
- bind refresh token to `client_id`, principal, resource, and scopes
- consent expires with the refresh token lifetime and can also be manually revoked

MCP must reject:

- normal QueryForge browser/API access tokens
- tokens with missing/wrong `typ`
- tokens with missing/wrong `aud`
- expired tokens
- revoked `jti`
- insufficient scopes

## OAuth Endpoints

Implement under a feature-local backend package:

```text
query-forge-api/app/features/mcp_oauth/
  __init__.py
  routes.py
  schemas.py
  service.py
  metadata_service.py
  client_registry.py
  authorization_code_service.py
  token_service.py
  consent_service.py
  serializers.py
```

Preserve stable import surfaces:

- `from app.features.mcp_oauth.routes import mcp_oauth_ns`
- `from app.features.mcp_oauth.service import MCPOAuthService`

Required endpoints:

| Endpoint | Host | Purpose |
| --- | --- | --- |
| `GET /.well-known/oauth-authorization-server` | API | OAuth server discovery metadata |
| `POST /oauth/register` | API | Dynamic client registration |
| `GET /oauth/authorize` | API | Authorization-code + PKCE start |
| `POST /oauth/token` | API | Code/refresh token exchange |
| `POST /oauth/revoke` | API | Revoke refresh/access token ids |
| `GET /.well-known/oauth-protected-resource` | MCP | MCP resource metadata |

Optional endpoints:

| Endpoint | Purpose |
| --- | --- |
| `GET /oauth/consent` | Render consent UI if not combined with authorize |
| `GET /oauth/sessions` | User/admin visible connected MCP sessions |
| `DELETE /oauth/sessions/<id>` | Disconnect/revoke ChatGPT session |

## Protected Resource Metadata

Serve from `https://mcp.query-forge.com/.well-known/oauth-protected-resource`.

Example:

```json
{
  "resource": "https://mcp.query-forge.com",
  "authorization_servers": ["https://api.query-forge.com"],
  "scopes_supported": ["qf:mcp:read", "qf:mcp:plan", "qf:mcp:preview"],
  "resource_documentation": "https://api.query-forge.com/docs/mcp"
}
```

Also add `WWW-Authenticate` challenges on MCP `401` responses with enough metadata for clients to rediscover the protected resource.

## Authorization Server Metadata

Serve from `https://api.query-forge.com/.well-known/oauth-authorization-server`.

Metadata must include:

- issuer
- authorization endpoint
- token endpoint
- registration endpoint
- revocation endpoint
- supported response types
- supported grant types
- supported scopes
- supported auth methods
- `code_challenge_methods_supported` including `S256`

## Login, MFA, and Consent UX

Use backend-rendered OAuth login/consent pages for v1.

Rationale:

- ChatGPT opens the OAuth flow in a browser redirect context.
- A backend-rendered flow avoids coupling OAuth success/failure to SPA routing.
- QueryForge can reuse existing `AuthService`, password checks, TOTP verification, and session cookies.

Required behavior:

- If the user is not logged in, show QueryForge login.
- If MFA is required, complete existing TOTP challenge flow.
- Show a concise consent screen describing requested scopes and resource.
- Consent must not grant new QueryForge permissions.
- Consent only allows ChatGPT to act through MCP within existing QueryForge permissions.

Consent copy should say:

```text
Allow ChatGPT to access QueryForge semantic metadata and preview governed query results for workspaces you already have access to.
```

## Relationship To QueryForge Login And Future SSO

Do not replace the current QueryForge browser/API login with the MCP OAuth wrapper in the first implementation pass.

The MCP OAuth wrapper is an authorization layer for remote MCP clients. QueryForge browser login is an application authentication/session concern. They should share underlying identity/session services over time, but MCP OAuth should not become the only login path for the QueryForge app.

Recommended direction:

```text
Phase 1: Build MCP OAuth wrapper for ChatGPT
Phase 2: Add a QueryForge auth-provider abstraction
Phase 3: Add Entra ID OIDC login as an optional provider
Phase 4: Optionally unify browser/API token issuance behind the same auth/token service
```

The generalized layer should be:

```text
Auth provider abstraction:
  local_password_totp
  entra_oidc
  future_okta_oidc
  future_saml_bridge if needed
```

This keeps local username/password/TOTP working while allowing enterprise SSO to be added per organization/workspace.

Target Entra flow:

```text
Microsoft Entra ID
  -> authenticates user through OIDC
  -> returns id_token / claims to QueryForge
  -> QueryForge maps issuer + subject to a QueryForge user
  -> QueryForge issues its own browser/API session token
  -> QueryForge RBAC/workspace/domain/MCP grants remain authoritative
```

Target MCP + SSO interaction:

```text
ChatGPT
  -> QueryForge OAuth authorize endpoint
  -> QueryForge login session may come from local login or Entra OIDC
  -> QueryForge issues mcp_access token
  -> MCP validates mcp_access token and enforces QueryForge access
```

The important boundary:

- OAuth answers whether ChatGPT is allowed to act as a connected client.
- OIDC answers how a human user signs into QueryForge.
- QueryForge RBAC and grants answer what the authenticated principal can access.

### Future Entra Data Model

When Entra SSO is added, introduce an external identity mapping instead of replacing QueryForge users.

Recommended table: `external_identities`

Fields:

- `id`
- `provider_key`
- `issuer`
- `subject`
- `email`
- `user_id`
- `created_at`
- `updated_at`
- `last_login_at`
- `disabled_at`

Recommended organization/workspace SSO config:

- provider type: `entra_oidc`
- Entra tenant id
- client id
- client secret reference
- allowed issuer
- allowed email domains
- JIT provisioning enabled/disabled
- default workspace assignment policy
- group-to-role mapping policy, optional

Security decisions:

- Do not trust Entra groups as QueryForge roles by default.
- Map Entra groups to QueryForge roles explicitly if needed.
- Keep QueryForge as the source of truth for workspace membership, domain visibility, MCP grants, and preview rights.
- Keep a local break-glass admin login path even when SSO is enabled.
- Treat SSO account linking as security-sensitive and auditable.

## Database Model

Add migration-backed tables.

### `workspace_mcp_settings`

Workspace-specific MCP enablement and policy toggles.

Columns:

- `workspace_id`
- `enabled`
- `enabled_by`
- `enabled_at`
- `disabled_by`
- `disabled_at`
- `default_preview_row_limit`
- `max_preview_row_limit`
- `block_sensitive_domains`
- `created_at`
- `updated_at`

### `oauth_clients`

Dynamic client registrations from ChatGPT.

Columns:

- `client_id`
- `client_secret_hash` nullable
- `client_name`
- `redirect_uris` JSON
- `grant_types` JSON
- `response_types` JSON
- `scope`
- `token_endpoint_auth_method`
- `client_uri`
- `logo_uri`
- `contacts` JSON
- `created_at`
- `expires_at`
- `revoked_at`

### `oauth_authorization_codes`

Short-lived authorization codes.

Columns:

- `code_hash`
- `client_id`
- `principal_type`
- `principal_id`
- `redirect_uri`
- `resource`
- `scope`
- `code_challenge`
- `code_challenge_method`
- `nonce`
- `state_hash` nullable
- `created_at`
- `expires_at`
- `consumed_at`

### `oauth_refresh_tokens`

Rotating refresh tokens.

Columns:

- `token_hash`
- `client_id`
- `principal_type`
- `principal_id`
- `resource`
- `scope`
- `created_at`
- `expires_at`
- `rotated_at`
- `revoked_at`
- `replaced_by_hash` nullable

### `mcp_principal_grants`

Explicit MCP access channel grants.

Columns:

- `id`
- `principal_type`
- `principal_id`
- `workspace_id`
- `enabled`
- `allowed_tools` JSON
- `allowed_domain_keys` JSON nullable
- `can_preview`
- `preview_row_limit`
- `created_by`
- `created_at`
- `updated_at`
- `expires_at`
- `revoked_at`

### `oauth_consents`

Optional but recommended.

Columns:

- `id`
- `client_id`
- `principal_type`
- `principal_id`
- `resource`
- `scope`
- `granted_at`
- `revoked_at`

### `mcp_app_clients`

App-principal credentials and ownership metadata for non-human MCP integrations.

Columns:

- `client_id`
- `client_secret_hash`
- `display_name`
- `description`
- `owning_workspace_id`
- `owner_user_id`
- `created_by`
- `created_at`
- `last_used_at`
- `expires_at`
- `revoked_at`
- `rotation_required_at`

### `mcp_oauth_audit_log`

Indefinite DB-backed audit trail for OAuth and MCP authorization decisions.

Columns:

- `id`
- `event_type`
- `principal_type`
- `principal_id`
- `client_id`
- `workspace_id`
- `requested_resource`
- `requested_scopes`
- `tool_name`
- `domain_key`
- `saved_query_id`
- `decision`
- `denial_reason`
- `row_count_returned`
- `rate_limit_bucket`
- `trace_id`
- `details_json`
- `created_at`

## Nginx Topology

Production routing:

```text
api.query-forge.com/.well-known/oauth-authorization-server -> Flask API
api.query-forge.com/oauth/* -> Flask API

mcp.query-forge.com/.well-known/oauth-protected-resource -> MCP process
mcp.query-forge.com/mcp -> MCP process
```

Forward required headers:

- `Authorization`
- `Content-Type`
- `Mcp-Session-Id`
- `X-Forwarded-Proto`
- `X-Forwarded-Host`
- `X-Forwarded-For`

Expose required response headers:

- `Mcp-Session-Id`
- `WWW-Authenticate`

## Environment Variables

Add explicit runtime configuration:

```text
MCP_RESOURCE_URL=https://mcp.query-forge.com
MCP_ENABLED=false
MCP_REQUIRE_WORKSPACE_ENABLEMENT=true
MCP_REQUIRE_CHANNEL_GRANT=true
MCP_REQUIRE_QUERY_STUDIO_FOR_PREVIEW=true
MCP_INCLUDE_RAW_SQL=false
MCP_DEFAULT_PREVIEW_ROW_LIMIT=100
MCP_MAX_PREVIEW_ROW_LIMIT=500
MCP_RATE_LIMIT_PER_USER_PER_MINUTE=60
MCP_RATE_LIMIT_PER_CLIENT_PER_MINUTE=120
MCP_RATE_LIMIT_PREVIEW_PER_USER_PER_MINUTE=10
MCP_BLOCK_SENSITIVE_DOMAINS=false
OAUTH_ISSUER_URL=https://api.query-forge.com
OAUTH_ACCESS_TOKEN_TTL_SECONDS=3600
OAUTH_AUTH_CODE_TTL_SECONDS=300
OAUTH_REFRESH_TOKEN_TTL_SECONDS=1209600
OAUTH_CLIENT_TTL_SECONDS=2592000
OAUTH_ALLOWED_REDIRECT_HOSTS=chatgpt.com
OAUTH_REQUIRE_PKCE=true
OAUTH_ALLOWED_CODE_CHALLENGE_METHODS=S256
OAUTH_ENABLE_DYNAMIC_CLIENT_REGISTRATION=true
OAUTH_ENABLE_REFRESH_TOKENS=true
OAUTH_CONSENT_EXPIRES_WITH_REFRESH_TOKEN=true
OAUTH_ENABLE_APP_CLIENT_AUTH=true
```

Production defaults:

- require HTTPS issuer/resource URLs
- require PKCE
- globally disable MCP until explicitly enabled
- require per-workspace MCP enablement before any human or app MCP access is allowed
- require MCP channel grants
- reject raw SQL by default
- keep preview-only behavior
- require existing `query_studio` access for preview tools
- apply coarse per-user/per-client/per-preview rate limits before production enablement
- do not block known-sensitive domains by default when the user can already see them in QueryForge UI; keep `MCP_BLOCK_SENSITIVE_DOMAINS` as an operational flag for stricter deployments

## Audit Requirements

Log every OAuth and MCP authorization decision with:

- event type
- principal type
- principal id
- client id
- workspace id
- requested resource
- requested scopes
- tool name
- domain key
- saved query id, when applicable
- allowed/denied
- denial reason
- row count returned for preview calls
- trace id / correlation id
- rate-limit bucket and limit decision, when applicable

High-value audit events:

- dynamic client registration
- authorization grant approved/denied
- authorization code exchanged
- refresh token rotated/revoked
- MCP token rejected
- MCP tool denied by channel grant
- MCP tool denied by workspace/domain/RBAC
- preview result returned
- rate limit exceeded
- app principal credential issued/rotated/revoked

Retention:

- keep full OAuth/MCP audit history indefinitely in the database
- include audit export/backup in normal database backup strategy
- log files can rotate normally, but log rotation must not be the only retention mechanism for OAuth/MCP audit records

## Security Scenarios To Cover

- user signs in through ChatGPT but does not have `queryforge_mcp:user`
- user has MCP channel access but no workspace access
- user has workspace access but requested domain is hidden
- user has planning access but not preview access
- normal QueryForge browser JWT is sent to MCP
- token has wrong audience
- token has wrong issuer
- token has wrong type
- token has missing scope
- token is expired
- authorization code is replayed
- authorization code uses wrong `code_verifier`
- authorization code uses wrong `redirect_uri`
- `resource` changes between authorization and token exchange
- revoked client attempts token exchange
- app principal attempts to access ungranted workspace/domain/tool
- disabled global MCP flag rejects all MCP calls
- disabled workspace MCP setting rejects all human and app MCP calls for that workspace
- workspace admin enables MCP but does not grant a user `queryforge_mcp:user`
- workspace admin disables MCP after OAuth consent and refresh token issuance

## Phase 0 Test Matrix

The implementation should begin with focused tests before live OAuth endpoint wiring.

Phase 1 foundation tests:

- MCP OAuth config defaults are production-safe:
  - global MCP disabled by default
  - workspace enablement required by default
  - channel grants required by default
  - raw SQL disabled by default
  - refresh tokens and app-client auth are configurable
- MCP OAuth config normalizes invalid integer, CSV, and URL values safely.
- MCP SQLAlchemy models expose stable public table names.
- `workspace_mcp_settings` captures workspace enablement, preview limits, and sensitive-domain policy.
- `mcp_principal_grants` captures app-principal workspace/domain/tool/preview grants.
- OAuth code/refresh/consent models capture PKCE, rotation, expiry, revocation, and consent expiry.
- App client and audit models capture credential lifecycle and indefinite DB-backed audit shape.
- RBAC defines `queryforge_mcp:user`, `queryforge_mcp:preview`, and `queryforge_mcp:admin`.
- `workspace_admin` / `super_admin` do not implicitly receive `queryforge_mcp:*` end-user roles.

Later endpoint/evaluator tests:

- protected-resource metadata and authorization-server metadata are standards-shaped
- dynamic client registration validates redirect hosts
- authorization codes are one-time-use and PKCE-bound
- token exchange enforces `resource`, `aud`, `typ`, expiry, and scopes
- global MCP kill switch denies all MCP calls
- disabled workspace MCP setting denies all MCP calls for that workspace
- human MCP calls require `queryforge_mcp:user`
- preview calls require `queryforge_mcp:preview` and `query_studio`
- app principals are denied outside explicit workspace/domain/tool grants
- saved queries are limited to user-owned plus explicitly shared entries
- rate-limit decisions are audited
- revocation invalidates refresh-token and app-principal flows

## App Principal Future Path

Full app-principal authentication is in v1, not a future-only schema placeholder.

App-principal flow:

- admin creates MCP app client
- admin grants explicit workspace/domain/tool access
- app uses client credential or signed token exchange to obtain an MCP access token
- MCP token includes `principal_type=app`
- MCP resolver uses grant-only authorization, not human RBAC

App principals should require:

- owning organization/workspace
- explicit owner user
- explicit allowed tools
- explicit allowed domains
- row limits
- expiration
- revocation
- per-client rate limits

Admin UX:

- MCP access management should be available in the QueryForge admin UI in v1.
- The UI should allow workspace admins or higher to enable/disable MCP for a workspace.
- The UI should allow authorized admins to manage human MCP roles, app clients, app grants, revocation, expiration, allowed tools, allowed domains, preview enablement, and preview row limits for workspaces they administer.
- App principals should default to domain-scoped grants.
- Human principals should default to workspace-wide MCP channel access controlled by RBAC roles, with future optional grant-row narrowing.

## Implementation Phases

### Phase 0: Spec and Test Matrix

- Capture this design in repo docs.
- Add test plan entries for OAuth/MCP authorization behavior.
- Confirm redirect URI shown by ChatGPT app setup before production configuration.

### Phase 1: Data Model and Config

- Add OAuth/MCP grant migrations.
- Add workspace MCP settings migration.
- Add app-principal client migration.
- Add environment settings.
- Add config tests.
- No live OAuth endpoints yet.

### Phase 2: Metadata and Token Verifier

- Add protected-resource metadata endpoint to MCP server.
- Add OAuth authorization-server metadata endpoint to Flask.
- Add MCP token verifier that accepts only `mcp_access` tokens.
- Add `WWW-Authenticate` challenge behavior.
- Add focused tests for metadata and token rejection.

Implementation status:

- Implemented `GET /.well-known/oauth-protected-resource` in the standalone MCP app.
- Implemented `GET /.well-known/oauth-authorization-server` in the Flask API.
- Added documented Swagger-visible alias `GET /api/v1/mcp-oauth/authorization-server-metadata`.
- MCP bearer middleware now accepts only `mcp_access` tokens whose `aud` matches `MCP_RESOURCE_URL`.
- MCP metadata discovery remains public; protected MCP calls return a `WWW-Authenticate` challenge with `resource_metadata`.

### Phase 3: Dynamic Client Registration

- Implement `/oauth/register`.
- Persist client metadata.
- Validate redirect URI host allowlist.
- Add cleanup path for expired clients.
- Add tests for valid/invalid DCR.

Implementation status:

- Implemented unauthenticated `POST /oauth/register` under the Flask API.
- Dynamic registrations validate `redirect_uris` against `OAUTH_ALLOWED_REDIRECT_HOSTS`.
- Registrations reject unsupported grant types, response types, scopes, and token endpoint auth methods.
- Public PKCE clients use `token_endpoint_auth_method=none` and receive no client secret.
- Confidential registrations using `client_secret_basic` or `client_secret_post` receive a one-time plaintext client secret; only a SHA-256 hash is persisted.
- Expired dynamic client rows are deleted opportunistically before storing a new valid registration.

### Phase 4: Authorization Code + PKCE

- Implement `/oauth/authorize`.
- Add backend-rendered login/MFA/consent flow.
- Store hashed one-time authorization codes.
- Validate and echo `resource`.
- Add tests for PKCE and code replay.

Implementation status:

- Implemented `GET /oauth/authorize` to validate client, redirect URI, scopes, resource, and PKCE before rendering a backend-hosted login/consent form.
- Implemented `POST /oauth/authorize` to validate QueryForge credentials, require consent, check TOTP when enabled, persist a hashed one-time authorization code, and redirect to the registered client redirect URI.
- Authorization codes store only the SHA-256 code hash, PKCE challenge/method, principal, redirect URI, resource, scopes, nonce, optional state hash, expiry, and consumed timestamp.
- Added one-time consumption support for authorization codes so replayed codes are rejected by the service/repository seam used by the Phase 5 token endpoint.
- `resource` is validated against `MCP_RESOURCE_URL` and echoed back to the client redirect.

### Phase 5: Token and Revocation Endpoints

- Implement `/oauth/token`.
- Issue MCP-specific access tokens.
- Issue rotating refresh tokens when `OAUTH_ENABLE_REFRESH_TOKENS=true`.
- Implement `/oauth/revoke`.
- Add tests for token claims, refresh rotation, revocation, and audience binding.

Implementation status:

- Implemented `POST /oauth/token` for `authorization_code` and `refresh_token` grants.
- Authorization-code exchange consumes one-time authorization codes, validates the registered client, validates confidential client secrets when required, checks the original redirect URI, validates the `resource` value against the authorization code and `MCP_RESOURCE_URL`, and enforces PKCE verifier matching.
- Issued access tokens are MCP-only JWTs with `typ=mcp_access`, `iss=OAUTH_ISSUER_URL`, `aud=MCP_RESOURCE_URL`, client id, principal type/id, resource, scopes, `iat`, `exp`, and `jti`.
- Refresh tokens are opaque values stored only as SHA-256 hashes in `oauth_refresh_tokens`.
- Refresh-token grant use requires `OAUTH_ENABLE_REFRESH_TOKENS=true`, validates the active token hash, rotates the stored token, revokes the old token row, persists the replacement hash, and issues a fresh MCP access token.
- Implemented `POST /oauth/revoke` for idempotent persisted refresh-token revocation. Access-token revocation is accepted as a v1 no-op because access tokens are short-lived JWTs and the MCP verifier currently relies on expiry/audience/type validation.
- Added focused unit coverage for token claims, PKCE failures, confidential client auth, refresh rotation, refresh disablement, refresh revocation, repository behavior, and route wiring.

### Phase 6: MCP Principal Grants and App Auth

- Add `mcp_principal_grants` service/repository.
- Require `queryforge_mcp:user` or equivalent grant for all MCP tools.
- Require `queryforge_mcp:preview` plus existing QueryForge preview permissions for preview tools.
- Add app-principal client management service/repository.
- Add app credential/token exchange support.
- Add tests for channel access, workspace access, domain access, preview access, app grant enforcement, and app credential revocation.

Implementation status:

- Added repositories for `workspace_mcp_settings`, `mcp_principal_grants`, and `mcp_app_clients`.
- Added `MCPOAuthAccessService` for global MCP enablement, workspace MCP settings, and active app-principal grant lookup.
- Added `client_credentials` support to `POST /oauth/token` when `OAUTH_ENABLE_APP_CLIENT_AUTH=true`.
- App credentials are checked against active `mcp_app_clients` rows using SHA-256 secret hashes and issue MCP-only access tokens with `principal_type=app`.
- MCP request context now carries `principal_type`, `principal_id`, OAuth scopes, app-granted tools, preview row limit, and granted domain keys.
- MCP authenticator now enforces `MCP_ENABLED`, workspace MCP enablement, `queryforge_mcp:user` for human users, and `queryforge_mcp:preview` plus Query Studio access for preview capability.
- App principals bypass human workspace membership/RBAC but require an active `mcp_principal_grants` row for the requested workspace.
- Added a central MCP operation policy for tools/resources that enforces OAuth scopes, preview permission, app-granted tools, and app-granted domain keys before adapter execution.
- Added focused tests for repository decoding, app credential token issuance, disabled app auth, human channel-role denial, user preview gating, app grant context resolution, scope denial, tool denial, and domain denial.

### Phase 7: Admin UI, Rate Limits, Nginx, Docker, and Ops Docs

- Add admin UI for MCP access management.
- Add coarse per-user/per-client/per-preview rate limits.
- Update Nginx examples.
- Update Docker env templates.
- Update backend and MCP READMEs.
- Add deployment checklist and smoke-test commands.

Implementation status:

- Started Phase 7 with backend runtime safety controls before admin UI.
- Added `MCPRateLimiter` at the MCP tool/resource execution boundary.
- MCP calls now enforce per-principal, per-client, and preview-specific Valkey-backed rate-limit buckets before adapter execution.
- Rate-limit failures return MCP `RATE_LIMITED` errors and preserve retry metadata from the underlying rate-limit service.
- Added `MCPOAuthAuditRepository` for durable inserts into `mcp_oauth_audit_log`.
- MCP audit logging now persists allow/deny tool/resource events with principal, client, workspace, scopes, tool/resource name, domain/saved-query hints, decision, denial reason, preview row count, rate-limit buckets, trace id, and compact request details.
- Audit persistence is fail-open with warning logs so transient DB insert failures do not bypass authorization or break governed reads.
- Updated backend and MCP README runtime behavior documentation.
- Remaining Phase 7 work: admin UI/API management surfaces, nginx examples, Docker env templates, deployment checklist, and smoke-test commands.

### Phase 8: ChatGPT End-to-End Validation

- Register the remote MCP app in ChatGPT Developer Mode.
- Confirm OAuth redirect URI allowlist.
- Connect ChatGPT to `https://mcp.query-forge.com/mcp`.
- Validate read/planning/preview tool paths.
- Validate disconnect/revoke behavior.

## Non-Goals For v1

- no arbitrary SQL
- no writes, DDL, or DML
- no MCP admin mutation tools
- no workspace-admin/super-admin bypass of MCP channel grants
- no raw SQL returned by default
- no broad schema crawling
- no Entra JIT provisioning; require pre-created QueryForge users first and add JIT later

## Confirmed Decisions

- human MCP access uses `queryforge_mcp:*` RBAC roles
- `mcp_principal_grants` are required for app principals and available for optional future per-domain/tool narrowing
- MCP is default-deny in production with a global kill switch and per-workspace opt-in
- workspace admins or higher can enable MCP for a workspace, then grant specific users/apps access for that workspace
- `workspace_admin` / `super_admin` do not bypass MCP channel grants
- `workspace_admin` / `super_admin` do not automatically receive MCP end-user access just because they can administer MCP settings
- preview tools require `queryforge_mcp:preview` and existing `query_studio` access
- saved queries are limited to user-owned plus explicitly shared queries; workspace-global saved queries require explicit role/grant permission
- ChatGPT-facing deployments never expose raw SQL by default
- consent expires with refresh-token lifetime and can be manually revoked
- refresh tokens are implemented in v1 behind `OAUTH_ENABLE_REFRESH_TOKENS`
- full app-principal auth is included in v1
- admins manage MCP access through the QueryForge UI in v1
- human access starts workspace-wide; app access starts domain-scoped
- coarse rate limits are required before production preview enablement
- full OAuth/MCP audit records are retained indefinitely in the database and included in backup/retention operations
- sensitive-domain preview blocking is not enabled by default when the user can already see the data in QueryForge UI, but `MCP_BLOCK_SENSITIVE_DOMAINS` remains available as a stricter deployment flag
- future Entra SSO requires pre-created QueryForge users first; JIT provisioning is deferred

## Remaining Open Decision

1. Should QueryForge restrict OAuth/DCR to specific ChatGPT workspace or organization identifiers?
   - Context: user OAuth proves the QueryForge user, but it may not prove which ChatGPT workspace/account initiated the connection unless ChatGPT supplies stable organization/workspace metadata during registration or authorization.
   - Conservative approach: rely on QueryForge user OAuth for v1, log all DCR/client metadata, and add a deny/allowlist hook if ChatGPT exposes stable organization identifiers.
   - Stricter future approach: require customer-configured ChatGPT organization/workspace identifiers before accepting DCR or authorization.

## Acceptance Criteria

- ChatGPT can discover MCP protected-resource metadata.
- ChatGPT can discover QueryForge OAuth authorization-server metadata.
- ChatGPT can dynamically register a client.
- ChatGPT can complete authorization-code + PKCE login/consent.
- ChatGPT receives an MCP-specific access token with correct issuer, audience, type, scopes, and expiry.
- MCP rejects normal QueryForge browser/API JWTs.
- MCP rejects wrong audience/resource/scope tokens.
- MCP uses current QueryForge workspace/RBAC/domain visibility on every call.
- MCP preview remains preview-only, row-limited, and timeout-limited.
- Users/admins can revoke ChatGPT/MCP access.
- OAuth/MCP authorization decisions are auditable.
