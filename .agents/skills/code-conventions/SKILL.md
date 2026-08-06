---
name: code-conventions
description: "Coding standards, commit format, and development rules for this project. Activate when the user asks how to write code, format a commit, follow project conventions, or add new features."
---

## Python Style

- PEP 8: 4-space indent, `snake_case` functions, `PascalCase` classes
- Type hints on all public methods (follow `src/pipeline.py` as reference)
- Guard filesystem ops and subprocess calls with explicit error handling
- No ad-hoc patches — find root cause first

## TDD: Required for All New Code

For every new function:
1. Write a failing test and confirm it fails
2. Implement the minimal code to pass
3. Refactor, confirm all tests still pass
4. Branch coverage must remain ≥ 90%

## File Length

Keep files under 500 lines; split when exceeded.

## New Helper Placement

- CSV parsing helpers → near `_parse_*` methods in `src/pipeline.py`
- CLI/MCP layers → argument validation, logging, error translation only (no business logic)
- Tests → `test/` directory

## Commit Format

```
<type>: Short summary (≤60 chars)

## Implementation Details
- Specific change and reason

## Test Results
- All N tests successful (X new added)

🤖 Generated with Claude Code
Co-Authored-By: Claude <noreply@anthropic.com>
```

Types: `feat:`, `fix:`, `refactor:`, `test:`, `docs:`

Split commits by concern — bug fix, feature addition, and refactoring go in separate commits
(use `git add -p` for partial staging).

## Security

- Never commit `.env` or API keys (`.gitignore` already covers `.env`)
- Redirect large CSV outputs to `/tmp` or a caller-provided path; don't commit them

## Data-Driven Text (no hard-coded user-facing strings in `.py`)

User-facing Japanese text lives in data files, not in Python source, so it's editable and auditable
independently of code:

- **`data/rating_patterns.csv`**: per-pattern `quality_level`/`advice_text`/`warning_text` (loaded by
  `RuleBasedRatingAnalyzer._load_patterns()`).
- **`data/rating_messages.json`**: text common to *every* result regardless of pattern —
  `template_notice`, `general_disclaimer`, and the empty/unknown-pattern fallback text (loaded by
  `RuleBasedRatingAnalyzer._load_messages()`).
- **`data/mcp_tool_descriptions/place_ratings_analyze.md`**: the MCP tool description shown to MCP
  clients/AI agents (loaded by `src/server.py:_load_tool_description()`, passed via
  `@mcp.tool(description=...)`). The function's own docstring is just a one-line pointer to this file.
  **Caveat**: `_PLACE_RATINGS_ANALYZE_DESCRIPTION` is loaded **once at server process startup**, not
  per-request. Editing this `.md` file has no effect on an already-running MCP server — it must be
  restarted for the new description to reach clients.
- **`data/mcp_tool_descriptions/server_instructions.md`**: FastMCP's server-level `instructions`
  (passed to `FastMCP(..., instructions=_SERVER_INSTRUCTIONS)` in `src/server.py`) — this is what
  shapes whether a client picks this server at all, independent of any one tool's own description
  (see cross-session memory `project_place_ratings_analyzer_naming_and_discoverability`: this lever
  measurably outperforms editing an individual tool's description for discoverability). **Claude
  Desktop reads only the first line of this file to summarize what the server is for** (e.g. in a
  connector/tool list) — put the single most important discoverability fact there, not buried
  further down.
