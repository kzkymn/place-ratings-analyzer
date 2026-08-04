---
name: mcp-server
description: "Start the FastMCP server for Claude Desktop or remote HTTP access. Activate when the user asks to run the MCP server, integrate with Claude Desktop, set up HTTP transport, or configure OAuth."
---

## Quick Start

The product path is Docker; see `setup-environment` skill for the full setup walkthrough
(WSL → Docker → build → Claude Desktop registration). Once the image is built:

```bash
# stdio mode (for Claude Desktop)
docker run -i --rm --shm-size=1g place-ratings-analyzer:latest python -m src.server

# HTTP mode (for same-machine MCP clients)
docker compose up --build   # → http://localhost:8888/mcp
```

For local development without Docker (running the server directly against a
pre-built environment — see `build-go` and `run-tests` skills first):

```bash
python -m src.server                                          # stdio
python -m src.server --transport http --host 127.0.0.1 --port 8000  # HTTP
```

## Transport Modes

| Mode | Command | Use case |
|------|---------|---------|
| stdio | `python -m src.server` | Claude Desktop |
| HTTP | `python -m src.server --transport http --host HOST --port PORT` | Same-machine MCP clients |

Claude Desktop must use stdio while this server runs on localhost: its HTTP/HTTPS custom
connectors originate from Anthropic's cloud and can never reach `localhost` (see Docker section
below).

## Docker

`Dockerfile` builds a self-contained image (Go scraper cloned from upstream at build time, Python/
FastMCP, Chromium) — see the file's comments for why a Playwright-driver-download workaround is
needed (upstream CDN outage, see `project_playwright_driver_cdn_breakage` in memory).

- `docker-compose.yml`: HTTP mode, no auth, `http://localhost:8888/mcp`.
- **Claude Desktop connects via stdio, not HTTP.** `claude_desktop_config.json` runs `docker run -i
  --rm --shm-size=1g place-ratings-analyzer:latest python -m src.server` directly. Claude Desktop's
  HTTP/HTTPS custom-connector feature cannot be used for this while the server runs on localhost:
  the connector's traffic originates from Anthropic's cloud, not the local machine, so `localhost`
  is unreachable in principle no matter what TLS/reverse-proxy setup is added locally (this was
  tried and confirmed impossible — see `project_oauth_remote_mcp_setup` in memory). The HTTP mode
  still exists for the OAuth E2E test (`tools/oauth_e2e_client.py`) and for any other MCP client running
  on the same machine.
- **Remote use of this server (from clients beyond the same machine) is possible** by deploying to
  Google Cloud Run with OAuth enabled — see "Remote Deployment (Google Cloud Run)" below. This is
  the route Claude Desktop's custom-connector feature requires (localhost can never work there —
  see the stdio bullet above). ChatGPT Desktop instead has a vendor-side tunnel option (OpenAI's
  Secure MCP Tunnel): the server stays on the local machine and the tunnel client connects
  outbound only, so no publishing is needed for that client.

## Architecture

```
Claude Desktop       →  stdio  →  src/server.py  →  GoogleMapsPipeline
Same-machine client  →  HTTP   →  http://host:port/mcp/  →  src/server.py
```

Key files:
- `src/server.py`: FastMCP app + `place_ratings_analyze()` tool definition; OAuth setup; argparse entry point (`python -m src.server`)
- `Dockerfile`: builds the self-contained image (Go build + Playwright driver + Python/FastMCP); this is the product's setup implementation

## Parameter Constraints (enforced in src/server.py)

- `max_results` ≤ 100
- `concurrency` default 8, max 16
- Response returns first 10 results to avoid MCP payload limits

## OAuth (optional, HTTP mode only)

**Why**: once this server is deployed to a public cloud host (not just localhost, per the Docker
section above), OAuth is what lets you restrict usage to specific authorized Google accounts,
rather than leaving the tool callable by anyone who finds the URL.

`setup_oauth()` reads three environment variables — `MCP_CLIENT_ID`, `MCP_CLIENT_SECRET`,
`MCP_BASE_URL` — and returns `None` (no auth) if `MCP_CLIENT_ID` is unset. For the actual
deployment target (Cloud Run), these are set at deploy time via `gcloud run deploy
--set-env-vars`/`--set-secrets` (see `tools/deploy-cloud-run.sh`), not read from a local file.
There is no `.env`-based local convenience layer for this (removed 2026-08-02 along with
`python-dotenv` and `docker-compose.auth.yml` — it existed only to support repeated local OAuth
iteration during GoogleProvider's initial bring-up, which is done; re-add it only if that kind of
iteration becomes a recurring need again). Export the three variables directly (local testing), or
pass them via `-e`/`--set-env-vars`/`--set-secrets` (Docker/Cloud Run) before starting the server
in HTTP mode.

Security: HTTP mode has no auth by default and is intended for same-machine/LAN clients only,
unless OAuth is configured.

Implementation note: `setup_oauth()` doesn't pass `redirect_path` to `GoogleProvider`, so FastMCP's
default `/auth/callback` applies (not `/oauth/callback`) — this must match what's registered as the
authorized redirect URI in the Google Cloud Console. `required_scopes` is hardcoded to `openid` +
`userinfo.email` (not configurable via environment variables).

### Create a Google OAuth client

1. Open the [Google Cloud Console](https://console.cloud.google.com/); create a new project or
   select an existing one.
2. From the side menu, select "Google Auth Platform" → "Clients" → "Create Client".
3. If prompted to configure the consent screen: choose "External" (lets you add test users), enter
   the app name/support email/developer contact, save and continue.
4. On the OAuth client ID creation screen: **Application type** = Web application, any **Name**,
   and under **Authorized redirect URIs** add `http://localhost:8888/auth/callback` for local
   testing (match the port to whatever you actually run on). For a real deployment, also add the
   deployed `https://<host>/auth/callback` URL.
5. Click "Create" and copy the client ID and client secret shown.
6. To restrict who can log in, keep the consent screen in "Testing" publishing status and add
   allowed Google accounts under its "Test users" list (up to 100) — anyone not listed is blocked
   by Google before the request ever reaches this server. No application code or extra secret is
   needed for this.

### Test the flow

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

### Troubleshooting

- **`redirect_uri_mismatch`**: the redirect URI registered in the Google Cloud Console must match
  `MCP_BASE_URL` + `/auth/callback` exactly, including trailing slashes.
- **Consent screen doesn't appear**: verify the environment variables are actually set in the
  shell/container that starts the server (`python -c "import os; print(os.getenv('MCP_CLIENT_ID'))"`).

### References

- [FastMCP Google OAuth Integration](https://gofastmcp.com/integrations/google)
- [FastMCP Authentication Documentation](https://gofastmcp.com/servers/auth/authentication)
- [Google OAuth 2.0](https://developers.google.com/identity/protocols/oauth2)

## Remote Deployment (Google Cloud Run)

Below, `PROJECT_ID`, `REGION`, `SERVICE_NAME` are placeholders for the reader's own values (e.g.
`your-gcp-project-id` / `asia-northeast1` / `place-ratings-analyzer`, matching
`deploy-cloud-run.env.example`).

### 1. Prerequisites

- A GCP project with a billing account linked:
  ```bash
  gcloud billing projects link PROJECT_ID --billing-account=<billing account id>
  ```
  List available billing accounts with `gcloud billing accounts list`. If no billing account
  exists yet, one must be created via Google Cloud Console → "Billing" (payment method
  registration can't be done via CLI). Note there's a quota on how many projects one billing
  account can be linked to.
- Required APIs enabled:
  ```bash
  gcloud services enable run.googleapis.com artifactregistry.googleapis.com \
    secretmanager.googleapis.com firestore.googleapis.com --project=PROJECT_ID
  ```

### 2. Build and push the image

```bash
gcloud artifacts repositories create SERVICE_NAME \
  --project=PROJECT_ID \
  --repository-format=docker \
  --location=REGION

gcloud auth configure-docker REGION-docker.pkg.dev

docker build -t REGION-docker.pkg.dev/PROJECT_ID/SERVICE_NAME/SERVICE_NAME:latest .
docker push REGION-docker.pkg.dev/PROJECT_ID/SERVICE_NAME/SERVICE_NAME:latest
```

After creating the repository, confirm it isn't publicly readable. GCP IAM inherits down the
Organization → Project → Resource hierarchy, so an empty policy on the repository itself doesn't
guarantee it's private if a parent grants `allUsers` access. Check all three levels:

```bash
gcloud artifacts repositories get-iam-policy SERVICE_NAME --project=PROJECT_ID --location=REGION
gcloud projects get-iam-policy PROJECT_ID --format=json
gcloud projects describe PROJECT_ID --format="value(parent)"; gcloud organizations list
```

It's private if neither of the first two outputs contains `allUsers`/`allAuthenticatedUsers`, and
the project has no parent resource (i.e. it doesn't belong to an organization).

### 3. Create the Google OAuth client and register the secret

Create a Google OAuth client first (see this skill's OAuth section above for the Google Cloud
Console walkthrough), using `http://localhost:8888/auth/callback` as the redirect URI for now —
the Cloud Run redirect URI gets added in step 5, once the deployed URL is known.

Register the resulting client secret in Secret Manager. To avoid pasting the secret value into a
chat/terminal history, write it to a local file first and pipe only that file's content in:

```bash
gcloud secrets create mcp-client-secret --project=PROJECT_ID --data-file=-
```

(This reads the secret value from stdin — pipe the file's content into it, e.g. `cat
secret.txt | gcloud secrets create mcp-client-secret --project=PROJECT_ID --data-file=-`.)

Creating the secret alone isn't enough — Cloud Run's default runtime service account needs
explicit read access, or the container will fail to start once deployed:

```bash
gcloud iam service-accounts list --project=PROJECT_ID
# → find PROJECT_NUMBER-compute@developer.gserviceaccount.com

gcloud secrets add-iam-policy-binding mcp-client-secret \
  --project=PROJECT_ID \
  --member="serviceAccount:PROJECT_NUMBER-compute@developer.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"
```

Finally, restrict who can log in by keeping the OAuth consent screen (Google Cloud Console →
"APIs & Services" → OAuth consent screen configuration, currently labeled "Google Auth Platform"
in the UI — Google has renamed this menu before, so confirm the current label) in "Testing"
publishing status, and curating its "Test users" list with the Google accounts that should be
allowed in. This needs no application code: anyone not on the list is blocked by Google at the
consent screen itself, before any request reaches this server.

### 4. Create a Firestore database for OAuth session persistence

**Why**: Cloud Run scales to zero when idle, recycling the container. FastMCP's `OAuthProxy`
stores DCR client registrations and issued tokens on local disk by default, so every
scale-to-zero recycle wipes that storage and forces every user to re-authenticate. Setting
`MCP_OAUTH_FIRESTORE_DATABASE` (read by `setup_oauth()` in `src/server.py`) switches
`client_storage` to a `FirestoreStore` (from `py-key-value-aio[firestore]`) instead, so sessions
survive container restarts. This is optional — omit the variable to keep the plain local-file
storage, which is fine for local development but not for a scale-to-zero deployment.

```bash
gcloud firestore databases create --database=oauth-sessions \
  --project=PROJECT_ID --location=REGION --type=firestore-native

gcloud projects add-iam-policy-binding PROJECT_ID \
  --member="serviceAccount:PROJECT_NUMBER-compute@developer.gserviceaccount.com" \
  --role="roles/datastore.user"
```

(`PROJECT_NUMBER-compute@developer.gserviceaccount.com` is the same default Cloud Run runtime
service account granted `roles/secretmanager.secretAccessor` in step 3.)

### 5. Precompute the URL, then set the redirect URI

Cloud Run assigns a deterministic URL of the form
`https://SERVICE_NAME-PROJECT_NUMBER.REGION.run.app` when the service name is short enough (the
DNS segment must be ≤63 characters) — see [Manage Cloud Run
services](https://docs.cloud.google.com/run/docs/managing/services). Computing it before deploying
avoids a bootstrap problem: the deploy command always passes `--allow-unauthenticated` (Cloud Run
IAM is intentionally left off — see the "Why not..." note below for why access control is handled
by the app's OAuth instead), so deploying once without the OAuth env vars just to discover the
URL, then redeploying with them, would leave the service briefly reachable by anyone in between.

Add `https://SERVICE_NAME-PROJECT_NUMBER.REGION.run.app/auth/callback` to the OAuth client's
authorized redirect URIs (Google Cloud Console → "APIs & Services" → "Credentials" → the client
created in step 3), alongside the existing localhost one.

**Note**: after actually deploying (step 6), `gcloud run services describe` may report a
different-looking URL — Cloud Run's older hash-based form
(`https://SERVICE_NAME-<hash>-<region-code>.a.run.app`) — instead of this precomputed one. Both
are valid aliases for the same service (confirm with `curl`; both return the same response). What
matters is that the deployed app's own `MCP_BASE_URL` and the registered OAuth redirect URI agree
with each other, which precomputing the URL up front guarantees regardless of which form
`describe` later reports.

### 6. Deploy

Copy `deploy-cloud-run.env.example` (repo root) to `deploy-cloud-run.env` in the same place
(gitignored) and fill in the values gathered in steps 1–5 (`PROJECT_ID`, `REGION`,
`SERVICE_NAME`, `SECRET_NAME`, `FIRESTORE_DATABASE`, `MCP_CLIENT_ID`, `MCP_BASE_URL`), then run:

```bash
tools/deploy-cloud-run.sh
```

The script wraps `gcloud run deploy` with this project's flags — `--execution-environment=gen2`
(needed for Chromium's full Linux-compatibility requirements), `--session-affinity`,
`--concurrency`/`--timeout`/`--memory`/`--cpu` (starting points, not tuned values — adjust based
on observed scraping load), `--allow-unauthenticated`, and `--set-secrets`/`--set-env-vars` for
`MCP_CLIENT_SECRET`/`MCP_CLIENT_ID`/`MCP_BASE_URL`/`MCP_OAUTH_FIRESTORE_DATABASE` — and afterward
captures the deployed state under `.private/cloud-run-state/` (the same exported YAML shape
`gcloud run services replace` accepts) for drift auditing against future deploys. This lives under
`.private/` rather than being committed — it reveals the real project number, service account
email, OAuth client ID, and service URLs, not just secrets.

### 7. Verify and connect

Run the OAuth E2E smoke test against the real URL:

```bash
MCP_SERVER_URL="https://<your deployed host>/mcp" python tools/oauth_e2e_client.py
```

(This script requires `MCP_SERVER_URL` to be set — it has no localhost default, so it can't
silently run against the wrong target if you forget to set it.) Alternatively, connect directly
with a real MCP client and confirm a tool call actually returns data — that's a stronger check
than the script alone, since it exercises the exact client your users will use.

For Claude Desktop specifically:

1. Settings → Connectors → "Add custom connector".
2. Enter the MCP endpoint URL, e.g. `https://<your deployed host>/mcp` — the `/mcp` path is
   required; the bare host returns 404.
3. No manual Client ID/Secret entry is needed (see the OAuth section above on Dynamic Client
   Registration) — Claude registers itself automatically.
4. A browser OAuth flow starts: sign in with a Google account on the consent screen's "Test
   users" list, then approve.
5. Once authenticated, the server's tools become available.

If you also have this server registered locally over stdio (per the Docker section above), decide
whether to keep both registered — having the same tool name available from two connectors at once
can be confusing.

**Why not Cloud Run's own IAM / GCP Identity-Aware Proxy for access control?** Both were
considered and rejected. Cloud Run's IAM invoker check would require every request — including
the OAuth login pages themselves — to carry a GCP-signed ID token, which MCP clients never
present, so the login flow could never start. IAP acts as its own OAuth client toward Google
rather than exposing standard `/authorize`/`/token` endpoints that a third-party app (Claude
Desktop) could register against, so it can't substitute for what this server's own
`OAuthProxy`/`GoogleProvider` already does. Restricting who can use the deployment is handled
entirely by the consent screen's "Test users" list (step 3) instead.

### Troubleshooting: is it actually down?

A slow or seemingly-hung first request is usually a **cold start**, not an outage: this service
scales to zero when idle, and the next request has to boot a fresh container — including
Chromium — before it can respond. A first request taking several seconds to ~10s, followed by
fast responses afterward, is expected behavior, not a problem.

To check whether something is actually wrong instead:

```bash
# Is the service healthy, and which revision is currently serving?
gcloud run services describe SERVICE_NAME --project=PROJECT_ID --region=REGION \
  --format="value(status.conditions[0].type,status.conditions[0].status,status.latestReadyRevisionName)"
# expect: Ready  True  <revision name>

# Any actual errors in the last day?
gcloud logging read 'resource.type="cloud_run_revision" resource.labels.service_name="SERVICE_NAME" severity>=ERROR' \
  --project=PROJECT_ID --limit=10 --freshness=1d
```

If the service is `Ready: True` and there are no recent error-severity logs, a slow response was
almost certainly just a cold start — try the same request again.
