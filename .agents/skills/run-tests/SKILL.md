---
name: run-tests
description: "Run the pytest test suite, check coverage, or follow the TDD cycle. Activate when the user wants to run tests, check if tests pass, measure branch coverage, or write new tests."
---

## Commands

```bash
# Full suite
python -m pytest

# Single module
python -m pytest test/test_google_maps_pipeline.py

# Specific test by keyword
python -m pytest test/test_google_maps_pipeline.py -k histogram

# With coverage (90%+ branch required by project standard)
coverage run -m pytest && coverage report --show-missing
```

## Test Files

| File | What it covers |
|------|----------------|
| `test/test_google_maps_pipeline.py` | CSV parsing, rating analysis, histograms (~29 cases) |
| `test/test_fastmcp_integration.py` | MCP launch + client transport via FastMCP (requires a locally built scraper binary — see `build-go`) |
| `test/test_http_server.py` | HTTP transport args, server startup modes, OAuth config (9 tests) |
| `test/test_versions_env.py` | version-pin single source of truth (`versions.env`) |

## TDD Cycle (required for all new functions)

1. Write a failing test → confirm it fails (`pytest`)
2. Implement minimal code → confirm test passes
3. Refactor → confirm all tests still pass
4. Verify coverage stays at 90%+ branch

## All tests passing is not the checkpoint for these files

If the change touches `data/rating_patterns.csv`, `data/mcp_tool_descriptions/*.md`,
`data/rating_messages.json`, or `src/server.py`'s MCP response shape, a green `pytest` run
does not mean the change is done and does not mean it's time to ask "commit now?" — it only
means the deterministic logic is correct. Whether a real client LLM actually behaves
differently is a separate, unverified question. Before reporting the change complete or
proposing next steps, rebuild the Docker image and run the `e2e-self-test` skill, unprompted.
(2026-07-19: this exact gap — presenting a green test run as a stopping point for these files
— recurred multiple times in one session even after being corrected once.)

## Test Design Principles

- Use `tempfile` for CSV I/O (no side effects on filesystem)
- Mock `subprocess.run` to eliminate Go scraper dependency in unit tests
- Cover boundary cases: empty data, malformed JSON, invalid numerics
- Test names describe behavior, not line numbers
