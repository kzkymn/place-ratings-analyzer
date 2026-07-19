---
name: run-pipeline
description: "Run the Google Maps scraping and analysis pipeline from the command line (dev/smoke-test utility). Activate when the user wants to execute a Google Maps search without an MCP client, scrape data, run tools/cli.py, or verify the pipeline works."
---

## Steps

1. Ensure Go binary is built (see `build-go` skill if missing)
2. Run the pipeline:
   ```bash
   python tools/cli.py "クエリ" --concurrency 8
   ```

Note: `tools/cli.py` is a dev/smoke-test utility. The product entry point is the MCP server
(`src/server.py`, see `mcp-server` skill); real usage is LLM-mediated via MCP.

## Key Flags

| Flag | Default | Notes |
|------|---------|-------|
| `--concurrency` | 8 | Optimal for 8-core CPU |
| `--max-results` | 20 | |
| `--output` | (none) | Path to save JSON results |
| `--keep-csv` | (none) | Path to keep intermediate CSV for debugging |
| `--scraper-path` | (auto) | Override Go scraper binary path |
| `--simple` | off | Skip details (business hours) |

Review-body fetching (`extra_reviews`) is disabled entirely. There is no CLI flag for it;
ratings/counts/distribution are always fetched, review text never is.

### Why: Google RPC API changed ~Dec 2025

During private development, this project could return actual review comment text, not just the
★1–5 count breakdown: `place_ratings_analyze()` included a `sample_reviews` field
(`src/pipeline.py`'s `extract_places()` parsed it from the `user_reviews_extended` CSV column).
That capability depended on `-extra-reviews`, a CLI flag of the vendored Go scraper
(`google-maps-scraper`, cloned from upstream at Docker build time; flag defined in
`runner/runner.go`) which collects up to ~300 full review texts per place.

Around December 2025, Google changed the RPC API that flag relies on. The scraper's fallback for
when RPC fails is DOM scrolling (`gmaps/reviews.go`, `maxScrollAttempts := 30`), which can hang for
up to 63s per place — unacceptable for an interactive MCP tool call. Rather than ship a feature
with that hang risk, this capability was cut before publishing: `extra_reviews` is a no-op (default
`False` in `src/pipeline.py`) and its parameter has been removed from `place_ratings_analyze()` in
`src/server.py`. As a result, this public version of the server cannot return review comment
text at all — only the ★1–5 count breakdown and pattern-based advice, which come from the place
page itself (a separate data path, unaffected by this flag) and remain fully functional. The
previous implementation is preserved as a commented-out block in `src/pipeline.py:extract_places()`
in case Google's upstream API stabilizes and this is revisited.

## Performance

Optimal concurrency is `--concurrency 8` (69% faster than the old default of 2; ~17s vs 56s).
The Go scraper (web scraping) is the bottleneck — 99.9% of runtime; Python parsing is 0.1%.

## Query Speed Guide

| Query type | Example | Time |
|------------|---------|------|
| Specific store name | `"新宿 五ノ神製作所"` | ~17s |
| Chain + area | `"渋谷 すき家"` | ~22s |
| Category search | `"渋谷 ラーメン"` | 40–170s (avoid) |

## Output

Console: rating distribution, histogram, hours  
JSON: pass `--output results.json`
