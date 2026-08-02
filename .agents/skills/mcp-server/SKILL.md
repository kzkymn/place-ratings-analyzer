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
- **Remote use of this server (from clients beyond the same machine) is a future goal, currently
  on hold.** Two distinct routes exist, which earlier versions of this doc conflated as "internet
  exposure":
  - **Publishing the server itself** on a public host with HTTPS. This is what Claude Desktop's
    custom-connector route requires (localhost can never work there — see the stdio bullet above).
    This project currently ships no TLS termination, so this route needs infrastructure that
    doesn't exist here yet.
  - **A vendor-side tunnel**, e.g. OpenAI's Secure MCP Tunnel for ChatGPT Desktop: the server
    stays on the local machine and the tunnel client connects outbound only, so no publishing is
    needed.

  **Deployment platform decided: Google Cloud Run** (2026-07-29) — chosen over AWS Lambda (its
  response streaming is one-directional only, incompatible with streamable HTTP's bidirectional
  session) and Fly.io (would need a hand-rolled session-affinity mechanism). Cloud Run has both
  scale-to-zero and a built-in session-affinity feature, and reuses the GCP project that already
  holds the working OAuth client. Not yet implemented —
  the server now resolves its port from `$PORT` (2026-07-30, `src/server.py`'s `--port` default
  and the `Dockerfile`'s `ENV PORT=8888` + `CMD` no longer pinning `--port`), so Cloud Run's
  injected port is honored automatically. Still outstanding: verifying Chromium's `/dev/shm`
  needs against Cloud Run's memory allocation (untested — the vendored `google-maps-scraper`
  has no `--no-sandbox`/launch-args handling, so gVisor compatibility is unverified). A first
  draft of the deploy script exists at `.private/deploy-cloud-run.sh`
  (`--execution-environment=gen2`, `--session-affinity`, `--concurrency`, `--timeout`,
  `--memory`/`--cpu`, `--allow-unauthenticated`, plus a post-deploy `gcloud run services
  describe --format export` snapshot for drift auditing) — untested, all tunable values are
  initial guesses, and it's kept private since it names actual project/service identifiers and
  hasn't been run yet. And restricting access to the intended handful of users. That restriction
  needs no application code: Cloud
  Run's own IAM invoker check was ruled out (it would block the OAuth login pages themselves,
  since MCP clients never present a GCP-signed ID token), so it's handled instead by keeping the
  Google OAuth consent screen in "Testing" publishing status and curating its built-in "Test
  users" list (Google blocks anyone else at the consent screen, before any request reaches this
  server) — no allowlist code or extra secret. See `project_oauth_remote_mcp_setup` in
  memory for the full comparison history and the GCP-side steps (Artifact Registry, Secret
  Manager, OAuth redirect URI update, live deploy) that are intentionally deferred pending user
  sign-off.

  An earlier Caddy-based LAN reverse proxy was retired once it became clear no client needed it:
  Claude Desktop works over stdio (the config-file route above, no HTTPS involved), and ChatGPT
  Desktop can use its tunnel. See the OAuth section below for why authentication matters once the
  server is genuinely published, and `project_oauth_remote_mcp_setup` in memory for the full
  history before resuming this.

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
--set-env-vars`/`--set-secrets` (see `.private/deploy-cloud-run.sh`), not read from a local file.
There is no `.env`-based local convenience layer for this (removed 2026-08-02 along with
`python-dotenv` and `docker-compose.auth.yml` — it existed only to support repeated local OAuth
iteration during GoogleProvider's initial bring-up, which is done; re-add it only if that kind of
iteration becomes a recurring need again). To exercise the OAuth flow locally, export the three
variables directly before running HTTP mode.

The end-user setup guide (`OAUTH_SETUP.md`) was withdrawn from the public repo and is kept as a
private draft until the cloud-deployment work resumes — see `project_oauth_remote_mcp_setup` in
memory for where it lives and why.  
Security: HTTP mode has no auth by default and is intended for same-machine/LAN clients only,
until that future cloud deployment happens.

Implementation note: `setup_oauth()` doesn't pass `redirect_path` to `GoogleProvider`, so FastMCP's
default `/auth/callback` applies (not `/oauth/callback`) — this must match what's registered as the
authorized redirect URI in the Google Cloud Console. `required_scopes` is hardcoded to `openid` +
`userinfo.email` (not configurable via environment variables).
