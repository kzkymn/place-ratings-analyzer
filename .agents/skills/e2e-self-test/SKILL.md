---
name: e2e-self-test
description: "Drive the deployed MCP server end-to-end via a non-interactive `claude -p` subprocess, without waiting on the user to restart their own session. Activate when verifying that a change to tool descriptions, server instructions, or advice wording actually changes real LLM behavior through the registered MCP server."
---

## Why this exists

Editing `data/mcp_tool_descriptions/*.md` or `data/rating_messages.json` only takes effect
once the Docker image is rebuilt (these are baked into the image; see `mcp-server` skill's
caveat about `_PLACE_RATINGS_ANALYZE_DESCRIPTION` loading once at server startup) and a
**fresh** Claude Code/Desktop session picks it up (the current session's tool list was
captured at connection time). Historically this meant asking the user to restart their
session and manually paste a query. This skill runs that same check as a subprocess instead.

## Prerequisites

1. `place-ratings-analyzer` MCP server registered at **user** scope and pointing at the
   Docker product path:
   ```bash
   claude mcp list   # should show: place-ratings-analyzer ... ✔ Connected
   ```
   If it points at a stale path or local scope, see `mcp-server` skill to re-register.
2. Docker image rebuilt with the change under test:
   ```bash
   docker build -t place-ratings-analyzer .
   ```
   Skipping this step is the most common false negative — the subprocess will faithfully
   exercise the *old* image.
3. A scratch working directory outside the repo (e.g. `~/work/for_claude`) so the
   sub-session's tool/session state doesn't interfere with this one. `-c/--continue`
   resumes "the most recent conversation **in the current directory**", so reusing this
   directory is also how multi-turn tests find their prior turn (see below).

## Running a single-turn check

```bash
cd ~/work/for_claude && claude -p "<query>" \
  --allowedTools "mcp__place-ratings-analyzer" \
  --output-format text
```

- `--allowedTools "mcp__place-ratings-analyzer"` grants every tool/resource this one MCP
  server exposes (including the `ResourcesAsTools`-generated `read_resource` wrapper) without
  a broad `--dangerously-skip-permissions`/`--permission-mode bypassPermissions` grant, which
  Claude Code's auto-mode classifier blocks for a nested session. Scoping to just this server
  is what gets approved.
- If the query needs external web access too (e.g. the mixed-ratings-workflow's Tabelog
  step), also allow `WebFetch`/`WebSearch`, or expect the sub-session to stop and describe
  what it would need — that's still a useful signal (it confirms tool *selection* worked even
  if it can't complete the full workflow unattended).
- `--output-format text` keeps the diff-able final answer only. Drop it (or use `json`) to
  inspect intermediate tool-call structure.

## Running a multi-turn check (e.g. a follow-up in the same conversation)

```bash
cd ~/work/for_claude && claude -p "<first query>" \
  --allowedTools "mcp__place-ratings-analyzer" --output-format text

cd ~/work/for_claude && claude -p "<follow-up query>" \
  --allowedTools "mcp__place-ratings-analyzer" --output-format text --continue
```

`--continue` resumes the most recent conversation in the same `cwd`, so the second call sees
the first call's context — this is how to test whether a trigger phrase is recognized as a
*follow-up* (e.g. "recommend X" then "the opposite of that"), not just as a fresh first
message.

## What this catches vs. doesn't

- **Catches**: whether a real LLM, working only from the shipped tool descriptions/server
  instructions (no memory of this conversation's design discussion), actually invokes the
  right tool/resource for a given phrasing, and whether the final wording avoids the
  reputation-risk patterns (evaluative headings, naming a real store alongside an accusation,
  leaking field names) - see `feedback-reputation-risk-in-advice-text` in cross-session
  memory for the full list of past failure patterns to check against.
- **Check what must be present, not only what must be absent.** Verifying "no forbidden
  patterns" alone lets behavioral regressions through: a 2026-07-19 run passed every
  absence check while a star5-dominant store sat inside the recommendation table with the
  best-looking numbers, so the reader would still just pick it — the warning existed but
  changed nothing. When the result set contains a star5-dominant candidate, verify the
  answer presents it *outside* the shared recommendation list/table, individually, as a
  "read the ★1/★2 review texts first" case. More generally: for each advice/notice the
  server attaches, define what the final answer should *do* if it worked, and check for
  that.
- **Instructions only steer composition from inside the tool result.** The same positioning
  rule sat in the tool description and was ignored; moving it into the notice text attached
  to the flagged store's entry fixed the behavior in one run. When a composition-stage
  behavior regresses, check where the instruction lives before rewording it.
- **Doesn't catch**: LLM output is non-deterministic, so a single passing run is evidence, not
  proof; rerun with phrasing variations before trusting a fix. It also doesn't replace static
  tests (`test_server_docstring.py` etc.) that pin the *content* of the instructions - this
  skill verifies the content actually *works* on a real model.

## Avoid leading the test

Two things quietly turn this into a leading question instead of a real trigger-discovery
test, both easy to fall into:

- **Naming the tool in the query** (e.g. "place_ratings_analyzeツールを使って..."). This only
  proves the pipe works end-to-end - it says nothing about whether the LLM would have chosen
  this tool on its own. Use it once as a connectivity sanity check, never as evidence a
  trigger phrase works.
- **Scoping `--allowedTools` to only this MCP server.** This is often necessary to get past
  the auto-mode classifier without a broad bypass grant (see above), but it also removes every
  competing option (WebSearch, the client's built-in place search, plain model knowledge) that
  the tool would need to win against in real usage. A query that "works" under this scoping
  only shows the LLM did *something* with the only tool available, not that it would prefer
  this tool when alternatives exist. For a trustworthy trigger-discovery test, allow the
  competing tools too (e.g. add `WebSearch`) and use natural phrasing that never names the
  tool - or fall back to the slower path of asking the user to test it in their own full
  session.

An initial round of this skill's checks (2026-07-17) used tool-named and
single-server-scoped queries; the result was informative for basic wiring (resource reads did
fire, the follow-up did re-trigger the workflow) but not conclusive for genuine trigger
discovery, and needed a separate check in a real session to confirm.
