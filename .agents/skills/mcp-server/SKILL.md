---
name: mcp-server
description: "Start the FastMCP server locally for Claude Desktop or same-machine HTTP access. Activate when the user asks to run the MCP server, integrate with Claude Desktop, or set up local HTTP transport."
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
FastMCP, Chromium) — see the file's comments and the `build-go` skill for why a
Playwright-driver-download workaround is needed (upstream CDN outage).

- `docker-compose.yml`: HTTP mode, no auth, `http://localhost:8888/mcp`.
- **Claude Desktop connects via stdio, not HTTP.** `claude_desktop_config.json` runs `docker run -i
  --rm --shm-size=1g place-ratings-analyzer:latest python -m src.server` directly. Claude Desktop's
  HTTP/HTTPS custom-connector feature cannot be used for this while the server runs on localhost:
  the connector's traffic originates from Anthropic's cloud, not the local machine, so `localhost`
  is unreachable in principle no matter what TLS/reverse-proxy setup is added locally (confirmed by
  testing a local TLS/reverse-proxy workaround directly). The HTTP mode
  still exists for the OAuth E2E test (`tools/oauth_e2e_client.py`) and for any other MCP client running
  on the same machine.
- **Remote use of this server (from clients beyond the same machine)** requires OAuth
  (`oauth-setup` skill) and deploying to Google Cloud Run (`cloud-run-deploy` skill). This is
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

## Related

- Configure OAuth for remote/HTTP access: `oauth-setup` skill
- Deploy or redeploy to Cloud Run: `cloud-run-deploy` skill
