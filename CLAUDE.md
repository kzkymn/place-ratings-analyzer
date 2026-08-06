# CLAUDE.md

This file provides guidance to Claude Code when working with this repository.
Detailed workflow skills are in `.agents/skills/` — the source of truth; `.claude/skills` is a
symlink to it so Claude Code auto-discovers them. For a human-facing setup/usage walkthrough
(no Claude Code required), see [README.md](README.md) (English, canonical; Japanese translation:
[README_ja.md](README_ja.md)) — this file covers architecture rationale,
conventions, and known issues that matter for doing dev work here, not step-by-step instructions.
Keep this file to a project overview and a skill index — put step-by-step or deep-dive detail in
`.agents/skills/`, not here.

## Project Architecture

The neutral component overview and data-flow diagram live in
[README.md § Architecture](README.md#architecture) (one fact, one place). This section only
records the decisions and constraints behind that picture:

- Delivered as an **MCP server** (FastMCP; stdio for Claude Desktop, HTTP for other same-machine
  MCP clients), shipped **only** as a self-contained Docker image (Go scraper + Python/FastMCP +
  Chromium); see `.agents/skills/setup-environment/` for the user-facing setup walkthrough and
  `.agents/skills/mcp-server/` for build/run/OAuth/Docker details.
- `tools/cli.py` is a dev/smoke-test utility, **not a product entry point** (decided 2026-07-14:
  real usage is always LLM-mediated via MCP).
- Local non-Docker execution (`python -m src.server` against a manually built environment) is for
  **development only** (running `pytest`, iterating on `src/`) — see `.agents/skills/build-go/`
  and `.agents/skills/run-tests/`. The product path is Docker; a Python-based auto-provisioning
  launcher existed here previously but was retired 2026-07-16 in favor of one setup
  implementation (the `Dockerfile`) — see `project_run_mcp_server_primary_entry` in
  cross-session memory for the full history.
- The Go scraper binary must exist at `google-maps-scraper/bin/google_maps_scraper`
  (see `.agents/skills/build-go/`).

## Essential Commands

Command details live in `.agents/skills/` (one fact, one place) — this section only routes:

- **Set up the environment from scratch** (WSL, Docker, image build, Claude Desktop registration): `.agents/skills/setup-environment/`
- **Build the Go scraper** (+ version pins for scraper/Go/Playwright driver): `.agents/skills/build-go/`
- **Run tests / TDD cycle / coverage**: `.agents/skills/run-tests/`
- **Start the MCP server** (stdio / HTTP / Docker / OAuth): `.agents/skills/mcp-server/`
- **Smoke-test the pipeline without MCP** (`tools/cli.py`): `.agents/skills/run-pipeline/`
- **Coding standards & commit format**: `.agents/skills/code-conventions/`

User-facing setup walkthrough (Claude Desktop registration etc.): [README.md](README.md).

## Known Limitations

This server cannot return review comment text — the scope is ratings, review counts, and
the ★1–★5 distribution. Google changed the RPC API that the text-collection path relied on
(around December 2025); the count breakdown comes from a separate data path and is
unaffected. This is a technical/dev-facing detail deliberately kept out of README.md (an
end-user reading only the README doesn't need it — the LLM surfaces the limitation
naturally if a user asks for review text). The full root-cause narrative is in
`.agents/skills/run-pipeline/`.

Remote MCP over the internet (OAuth + GCP-based deployment on Cloud Run) is documented: see
README.md § "Making this reachable from anywhere" for the user-facing summary and
`.agents/skills/mcp-server/` for the full deployment walkthrough.
