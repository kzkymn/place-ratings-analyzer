---
name: oauth-setup
description: "Set up or troubleshoot Google OAuth for this MCP server's HTTP mode (create the OAuth client, test the flow, fix redirect/consent issues). Activate when the user asks to configure OAuth, create a Google OAuth client, or debug an OAuth login/redirect problem for this server."
---

**Why**: once this server is deployed to a public cloud host (not just localhost), OAuth is what
lets you restrict usage to specific authorized Google accounts, rather than leaving the tool
callable by anyone who finds the URL. For the actual deployment target (Cloud Run), see the
`cloud-run-deploy` skill — this skill only covers the OAuth client itself.

`setup_oauth()` (in `src/server.py`) reads three environment variables — `MCP_CLIENT_ID`,
`MCP_CLIENT_SECRET`, `MCP_BASE_URL` — and returns `None` (no auth) if `MCP_CLIENT_ID` is unset.
For Cloud Run, these are set at deploy time via `gcloud run deploy --set-env-vars`/`--set-secrets`
(see `cloud-run-deploy` skill), not read from a local file. There is no `.env`-based local
convenience layer for this (removed 2026-08-02 along with `python-dotenv` and
`docker-compose.auth.yml` — it existed only to support repeated local OAuth iteration during
GoogleProvider's initial bring-up, which is done; re-add it only if that kind of iteration becomes
a recurring need again). Export the three variables directly (local testing), or pass them via
`-e`/`--set-env-vars`/`--set-secrets` (Docker/Cloud Run) before starting the server in HTTP mode.

Security: HTTP mode has no auth by default and is intended for same-machine/LAN clients only,
unless OAuth is configured.

Implementation note: `setup_oauth()` doesn't pass `redirect_path` to `GoogleProvider`, so FastMCP's
default `/auth/callback` applies (not `/oauth/callback`) — this must match what's registered as the
authorized redirect URI in the Google Cloud Console. `required_scopes` is hardcoded to `openid` +
`userinfo.email` (not configurable via environment variables).

## Create a Google OAuth client

1. Open the [Google Cloud Console](https://console.cloud.google.com/); create a new project or
   select an existing one.
2. From the side menu, select "Google Auth Platform" → "Clients" → "Create Client".
3. If prompted to configure the consent screen: choose "External" (lets you add test users), enter
   the app name/support email/developer contact, save and continue.
4. On the OAuth client ID creation screen: **Application type** = Web application, any **Name**,
   and under **Authorized redirect URIs** add `http://localhost:8888/auth/callback` for local
   testing (match the port to whatever you actually run on). For a Cloud Run deployment, also add
   the deployed `https://<host>/auth/callback` URL (see `cloud-run-deploy` skill step 5 for how to
   precompute it before the first deploy).
5. Click "Create" and copy the client ID and client secret shown.
6. To restrict who can log in, keep the consent screen in "Testing" publishing status and add
   allowed Google accounts under its "Test users" list (up to 100) — anyone not listed is blocked
   by Google before the request ever reaches this server. No application code or extra secret is
   needed for this.

## Test the flow

```bash
# Endpoint smoke test (no browser) — confirms OAuth metadata/protection are wired up
curl http://localhost:8888/.well-known/oauth-authorization-server   # expect 200 with authorize/token/register listed
curl -X POST http://localhost:8888/mcp \
  -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'               # expect 401 when unauthenticated
```

Connecting with an OAuth-capable MCP client (e.g. `fastmcp.Client(url, auth="oauth")`, or Claude,
which supports Dynamic Client Registration out of the box) starts the flow automatically: dynamic
client registration (DCR) → authorization URL issuance → Google consent in the browser → redirect
to the registered callback → token issuance. No manual Client ID/Secret entry is needed on the MCP
client side for a DCR-compliant client like Claude; that input is only relevant for servers that
don't support DCR (this one does, via FastMCP's `OAuthProxy`).

## Troubleshooting

- **`redirect_uri_mismatch`**: the redirect URI registered in the Google Cloud Console must match
  `MCP_BASE_URL` + `/auth/callback` exactly, including trailing slashes.
- **Consent screen doesn't appear**: verify the environment variables are actually set in the
  shell/container that starts the server (`python -c "import os; print(os.getenv('MCP_CLIENT_ID'))"`).

## Why not Cloud Run's own IAM / GCP Identity-Aware Proxy for access control?

Both were considered and rejected. Cloud Run's IAM invoker check would require every request —
including the OAuth login pages themselves — to carry a GCP-signed ID token, which MCP clients
never present, so the login flow could never start. IAP acts as its own OAuth client toward Google
rather than exposing standard `/authorize`/`/token` endpoints that a third-party app (Claude
Desktop) could register against, so it can't substitute for what this server's own
`OAuthProxy`/`GoogleProvider` already does. Restricting who can use the deployment is handled
entirely by the consent screen's "Test users" list (above) instead.

## References

- [FastMCP Google OAuth Integration](https://gofastmcp.com/integrations/google)
- [FastMCP Authentication Documentation](https://gofastmcp.com/servers/auth/authentication)
- [Google OAuth 2.0](https://developers.google.com/identity/protocols/oauth2)
