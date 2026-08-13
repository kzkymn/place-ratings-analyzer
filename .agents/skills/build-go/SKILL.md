---
name: build-go-scraper
description: "Build or rebuild the Go scraper binary. Activate when the Go binary is missing, scraper returns empty results, or the user asks to build or update the scraper."
---

## Build

```bash
cd google-maps-scraper
go build -o bin/google_maps_scraper .
```

Binary is expected at `google-maps-scraper/bin/google_maps_scraper`.

## Version Pins (`versions.env` is the source of truth)

All pins — scraper (`GMS_REF`), Go (`GO_VERSION`), Playwright driver (`PW_CLI_VERSION`) —
are defined once in `versions.env` at the repo root. Consumers read from it: the
`Dockerfile` sources it, `src/playwright_driver.py` parses it (loader lives in
`playwright_driver.load_versions()`). Edit that one file to bump a pin; the coupling
between `GMS_REF` and `PW_CLI_VERSION` is documented inline there.

Exception: the `Dockerfile`'s `FROM golang:X.Y-trixie` tag must be kept in sync with
`GO_VERSION`'s major.minor by hand (FROM cannot read files; a mismatch fails the build loudly).

## When to Rebuild

- Binary is missing (pipeline fails with file-not-found error)
- Scraper returns empty results (possible DOM selector change upstream)
- After changing the pinned scraper version (GMS_REF)

## Manual Setup (local development)

The product path (Docker) builds the scraper automatically at image build time — see
`setup-environment` skill. For local development (running `pytest` outside Docker):

```bash
git clone --depth 1 --branch <GMS_REF from versions.env> \
  https://github.com/gosom/google-maps-scraper.git
cd google-maps-scraper && go mod download
go build -o bin/google_maps_scraper .
```

Requires Go (version pinned as `GO_VERSION` in `versions.env`) installed manually:
https://go.dev/dl/

## Playwright Driver (clean environments)

The scraper's playwright-go dependency downloads its driver from a **dead CDN** (404 on clean
machines; local machines may only work because of a leftover `~/.cache/ms-playwright-go`).
`src/playwright_driver.py` assembles the driver from live sources instead; it runs automatically
from `GoogleMapsPipeline` at scrape time (local dev) and at Docker build time.

## Troubleshooting

**"could not convert to string" error** — upstream Go scraper API changed: check out the pinned
GMS_REF again (do not build from `main`; the version pins above assume the tagged release).
