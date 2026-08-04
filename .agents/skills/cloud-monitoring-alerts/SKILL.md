---
name: cloud-monitoring-alerts
description: "Set up or tune Cloud Monitoring alert policies (request-count spike, 5xx error rate, instance/CPU cost-runaway, OAuth failure proxy) with email notification for the deployed place-ratings-analyzer Cloud Run service. Activate when the user asks to set up monitoring alerts, add anomaly/traffic-spike detection, configure GCP alerting, or tune alert thresholds."
---

## Quick Start

```bash
tools/setup-cloud-monitoring-alerts.sh channel               # create/reuse the email notification channel
tools/setup-cloud-monitoring-alerts.sh log-metric             # create/update the OAuth log-based metric
tools/setup-cloud-monitoring-alerts.sh policy-request-count
tools/setup-cloud-monitoring-alerts.sh policy-error-rate
tools/setup-cloud-monitoring-alerts.sh policy-instance-cpu
tools/setup-cloud-monitoring-alerts.sh policy-oauth-failures
tools/setup-cloud-monitoring-alerts.sh all                    # run all of the above, in order

tools/setup-cloud-monitoring-alerts.sh --dry-run <subcommand> # print the gcloud command instead of running it
```

Sources `deploy-cloud-run.env` (repo root, gitignored) for `PROJECT_ID`/`REGION`/`SERVICE_NAME`,
same as `tools/deploy-cloud-run.sh` — one source of truth for the deployment target. This user
prefers GCP/cloud-mutating operations confirmed one command at a time rather than batch-approved;
prefer running subcommands individually (or reviewing `--dry-run` output first) over `all` in one
shot.

Every mutating subcommand is idempotent (create-or-update, keyed on email address / metric name /
policy `displayName`) — safe to rerun after editing a threshold.

## What Each Alert Covers

| Alert | Metric | Default threshold | Tunable via (top of script) |
|---|---|---|---|
| Request count spike | `run.googleapis.com/request_count` | >100 per 5 min | `REQUEST_COUNT_THRESHOLD` |
| 5xx error rate spike | `run.googleapis.com/request_count` (MQL ratio) | >20% with ≥5 requests/5 min | `ERROR_RATIO_THRESHOLD`, `ERROR_RATIO_MIN_REQUESTS` |
| Instance/CPU spike | `run.googleapis.com/container/instance_count`, `.../cpu/utilizations` | >3 active instances OR CPU p99 >90%, sustained 3 min | `INSTANCE_COUNT_THRESHOLD`, `CPU_UTILIZATION_THRESHOLD` |
| OAuth failure spike (proxy) | `logging.googleapis.com/user/oauth_auth_failures` | >3 per 10 min | `OAUTH_FAILURE_THRESHOLD` |

All four notify the same email channel, address set via the required `ALERT_EMAIL` env var (same
as `PROJECT_ID`/`REGION`/`SERVICE_NAME`, no default).
Generated policy JSON is saved under `.private/cloud-monitoring-alerts/` (gitignored) for audit/diff,
same pattern as `deploy-cloud-run.sh`'s `.private/cloud-run-state/`.

Thresholds are starting points for a low-traffic, scale-to-zero personal-scale project, not tuned
values — revisit after observing real traffic.

## Known Limitation: OAuth Alert Is a Proxy Signal

`src/server.py` has no dedicated per-request OAuth failure logging — only one-time startup
messages via `print(..., file=sys.stderr)`. Actual OAuth request handling is delegated entirely to
the third-party `fastmcp` library's `GoogleProvider`/`OAuthProxy` (imported at `src/server.py:113`),
which isn't exposed as a hook/callback from this codebase.

The `oauth_auth_failures` log-based metric therefore counts any Cloud Run stderr line at
`severity>=WARNING` whose text matches `/oauth|token|auth/i` — a coarse proxy, not a precise
auth-failure counter. It can undercount (failures logged below WARNING) or overcount (unrelated
warning text happening to match the regex).

Improving precision would require adding structured logging for auth failures in `src/server.py`
— app code, needing tests per this repo's TDD convention — which is out of scope for this
infra/ops task. Revisit only if the proxy signal proves too noisy in practice.

## Verification

"The script ran without error" is not sufficient — verify end-to-end:

1. `gcloud alpha monitoring policies list --project="$PROJECT_ID" --format="table(displayName,enabled,combiner)"`
   — expect 4 rows, all `enabled=True`.
2. `gcloud alpha monitoring channels describe <channel-name> --format=json` — there is no
   `verify`/test-send CLI subcommand; use Console → Monitoring → Alerting → Notification channels
   → "Send Test Notification" if you need to confirm delivery without waiting for a real alert.
3. `gcloud alpha monitoring policies describe <name> --format=json`, diff against the
   corresponding file under `.private/cloud-monitoring-alerts/` — especially the MQL condition in
   the error-rate policy, since a subtle query problem can be accepted by the API without erroring
   loudly, then silently never fire.
4. Synthetic fire test (one policy at a time, not batched):
   - **OAuth policy** (safest to trigger — no real traffic needed):
     ```bash
     REVISION=$(gcloud run services describe "$SERVICE_NAME" --project="$PROJECT_ID" --region="$REGION" \
       --format='value(status.latestReadyRevisionName)')
     for i in 1 2 3 4; do
       gcloud logging write "run.googleapis.com%2Fstderr" "synthetic test: oauth token auth failure #$i" \
         --severity=WARNING --project="$PROJECT_ID" --payload-type=text \
         --monitored-resource-type=cloud_run_revision \
         --monitored-resource-labels=service_name="$SERVICE_NAME",revision_name="$REVISION",location="$REGION",configuration_name="$SERVICE_NAME"
     done
     ```
     Wait ~5 min, confirm the email actually arrives.
   - **Request-count / instance-CPU**: temporarily lower the relevant threshold, rerun only that
     subcommand, generate real traffic (curl / `tools/oauth_e2e_client.py`), confirm email, then
     restore the default and rerun.
   - **5xx error rate**: deliberately forcing a 5xx is unsafe to do against the live service.
     Accepted verification gap — validated via the `describe`/diff structural check (step 3) only,
     not a live fire test.

### Verification Log

| Alert | Live-fire confirmed? | Date | Notes |
|---|---|---|---|
| Request count spike | Not yet | | |
| 5xx error rate spike | Not live-fire tested (accepted gap) | 2026-08-04 | Structural check only — see "5xx error rate" above |
| Instance/CPU spike | Not yet | | |
| OAuth failure spike | **Confirmed** | 2026-08-04 | 4 synthetic WARNING-severity log lines written via `gcloud logging write`; email arrived at the `ALERT_EMAIL` address within ~10 min. Subject line was the condition's displayName ("oauth_auth_failures > 3 per 10 min"), not the policy's `documentation.content` — expect the proxy-signal caveat text further down in the email body, not the subject. This confirms the shared pipeline (channel → policy → notification) works end-to-end; the other 3 policies use the same channel and standard `conditionThreshold`, so this is a reasonable signal for them too, but each should still be confirmed independently per the steps above. |

Update this table as each alert is actually confirmed to deliver email, so a future reader knows
how much to trust each one.
