#!/usr/bin/env bash
# Deploy this MCP server to Google Cloud Run with OAuth enabled.
#
# Prerequisites (see the "Remote Deployment (Google Cloud Run)" section of
# .agents/skills/mcp-server/SKILL.md for the full walkthrough):
#   - Image built and pushed to Artifact Registry (the tag this script deploys)
#   - A Google OAuth client created, its client secret registered in Secret
#     Manager, and the Cloud Run default service account granted
#     roles/secretmanager.secretAccessor on it
#   - A Firestore database created, with the same service account granted
#     roles/datastore.user on it (needed so OAuth sessions survive Cloud Run's
#     scale-to-zero container recycling - without this, every cold start wipes
#     all issued tokens and forces users to re-authenticate)
#   - The OAuth consent screen's "Test users" list up to date
#
# All values below are required environment variables - either export them
# before running, or copy deploy-cloud-run.env.example (at the repo root) to
# deploy-cloud-run.env in the same place (gitignored) and fill in real values;
# this script sources that file automatically if present.

set -euo pipefail

CONFIG_FILE="$(dirname "$0")/../deploy-cloud-run.env"
if [[ -f "${CONFIG_FILE}" ]]; then
  # shellcheck disable=SC1090
  source "${CONFIG_FILE}"
fi

: "${PROJECT_ID:?Set PROJECT_ID (GCP project ID)}"
: "${REGION:?Set REGION (e.g. asia-northeast1)}"
: "${SERVICE_NAME:?Set SERVICE_NAME (Cloud Run service name)}"
: "${SECRET_NAME:?Set SECRET_NAME (Secret Manager secret holding MCP_CLIENT_SECRET)}"
: "${FIRESTORE_DATABASE:?Set FIRESTORE_DATABASE (Firestore database name for OAuth session storage)}"
: "${MCP_CLIENT_ID:?Set MCP_CLIENT_ID (Google OAuth client ID)}"
: "${MCP_BASE_URL:?Set MCP_BASE_URL (the public URL this service is deployed at)}"

IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${SERVICE_NAME}/${SERVICE_NAME}:latest"

# --- Resource sizing (starting points, not tuned values - adjust based on
#     observed scraping load) ---
EXECUTION_ENVIRONMENT="gen2"                    # needed for Chromium's full Linux-compatibility requirements
CONCURRENCY="${CONCURRENCY:-4}"
TIMEOUT="${TIMEOUT:-900s}"
MEMORY="${MEMORY:-2Gi}"
CPU="${CPU:-2}"

gcloud run deploy "${SERVICE_NAME}" \
  --project="${PROJECT_ID}" \
  --region="${REGION}" \
  --image="${IMAGE}" \
  --execution-environment="${EXECUTION_ENVIRONMENT}" \
  --session-affinity \
  --concurrency="${CONCURRENCY}" \
  --timeout="${TIMEOUT}" \
  --memory="${MEMORY}" \
  --cpu="${CPU}" \
  --allow-unauthenticated \
  --set-secrets="MCP_CLIENT_SECRET=${SECRET_NAME}:latest" \
  --set-env-vars="MCP_CLIENT_ID=${MCP_CLIENT_ID},MCP_BASE_URL=${MCP_BASE_URL},MCP_OAUTH_FIRESTORE_DATABASE=${FIRESTORE_DATABASE}"
# --allow-unauthenticated leaves Cloud Run's own IAM invoker check off; access
# control is instead handled entirely by the app's OAuth + the Google consent
# screen's "Test users" list (see the OAuth section of SKILL.md for why: MCP
# clients never present a GCP-signed ID token, so Cloud Run's IAM check would
# block the OAuth login pages themselves).

# --- Post-deploy: capture actual state for drift auditing ---
# `--format export` is Cloud Run's editable-YAML form, the same shape
# `gcloud run services replace` accepts - diffing this against the previous
# capture surfaces unintended drift between deploys. Written under .private/
# (gitignored, never committed) since it contains the real project number,
# service account email, OAuth client ID, and service URLs - not just secrets.
STATE_DIR="$(dirname "$0")/../.private/cloud-run-state"
mkdir -p "${STATE_DIR}"
gcloud run services describe "${SERVICE_NAME}" \
  --project="${PROJECT_ID}" \
  --region="${REGION}" \
  --format=export \
  > "${STATE_DIR}/${SERVICE_NAME}-$(date -u +%Y%m%dT%H%M%SZ).yaml"
