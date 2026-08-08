---
name: cloud-run-deploy
description: "Deploy or redeploy this MCP server to Google Cloud Run (first-time setup and routine redeploys), and check whether the deployed service is actually down. Activate when the user asks to deploy to Cloud Run, redeploy, publish an update, or troubleshoot a Cloud Run outage."
---

Below, `PROJECT_ID`, `REGION`, `SERVICE_NAME` are placeholders for the reader's own values (e.g.
`your-gcp-project-id` / `asia-northeast1` / `place-ratings-analyzer`, matching
`deploy-cloud-run.env.example`).

## Redeploying (already set up)

```bash
tools/deploy-cloud-run.sh
```

**Before running it**: if a previous deploy used `--no-traffic`/`--tag` (isolated debugging),
the service is pinned to a manual traffic split, and this plain deploy will leave the new
revision at 0% traffic, silently. Restore auto-tracking first:

```bash
gcloud run services update-traffic SERVICE_NAME --project=PROJECT_ID --region=REGION --to-latest
```

Never seen this service before? Skip to "First-time setup" below instead.

## Is it actually down?

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

## First-time setup

OAuth client creation is a separate concern — see the `oauth-setup` skill for step 3 below.

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

Create a Google OAuth client first (see the `oauth-setup` skill), using
`http://localhost:8888/auth/callback` as the redirect URI for now — the Cloud Run redirect URI
gets added in step 5, once the deployed URL is known.

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
IAM is intentionally left off — see the `oauth-setup` skill's "Why not Cloud Run's own IAM..."
note for why access control is handled by the app's OAuth instead), so deploying once without the
OAuth env vars just to discover the URL, then redeploying with them, would leave the service
briefly reachable by anyone in between.

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
`SERVICE_NAME`, `SECRET_NAME`, `FIRESTORE_DATABASE`, `MCP_CLIENT_ID`, `MCP_BASE_URL`), then run
the command in "Redeploying" above.

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
3. No manual Client ID/Secret entry is needed (Dynamic Client Registration — see `oauth-setup`
   skill) — Claude registers itself automatically.
4. A browser OAuth flow starts: sign in with a Google account on the consent screen's "Test
   users" list, then approve.
5. Once authenticated, the server's tools become available.

If you also have this server registered locally over stdio (`mcp-server` skill), decide whether
to keep both registered — having the same tool name available from two connectors at once can be
confusing.
