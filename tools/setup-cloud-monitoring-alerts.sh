#!/usr/bin/env bash
# Set up Cloud Monitoring alert policies (request-count spike, 5xx error
# rate, instance/CPU cost-runaway, OAuth-failure proxy) with email
# notification for the deployed place-ratings-analyzer Cloud Run service.
# See .agents/skills/cloud-monitoring-alerts/SKILL.md for the full walkthrough
# and known limitations (in particular: the OAuth alert is a coarse proxy
# signal, not a precise per-request auth-failure counter).
#
# Usage:
#   tools/setup-cloud-monitoring-alerts.sh [--dry-run] <subcommand>
#
# Subcommands (each is a single reviewable unit of gcloud work):
#   channel               create/reuse the email notification channel
#   log-metric            create/update the OAuth log-based metric
#   policy-request-count
#   policy-error-rate
#   policy-instance-cpu
#   policy-oauth-failures
#   all                    run all of the above, in order
#
# All values below are required environment variables - either export them
# before running, or copy deploy-cloud-run.env.example (at the repo root) to
# deploy-cloud-run.env in the same place (gitignored) and fill in real
# values; this script sources that file automatically if present, same as
# tools/deploy-cloud-run.sh.

set -euo pipefail

CONFIG_FILE="$(dirname "$0")/../deploy-cloud-run.env"
if [[ -f "${CONFIG_FILE}" ]]; then
  # shellcheck disable=SC1090
  source "${CONFIG_FILE}"
fi

: "${PROJECT_ID:?Set PROJECT_ID (GCP project ID)}"
: "${REGION:?Set REGION (e.g. asia-northeast1)}"
: "${SERVICE_NAME:?Set SERVICE_NAME (Cloud Run service name)}"
: "${ALERT_EMAIL:?Set ALERT_EMAIL (address to receive alert notifications)}"

# --- Thresholds (starting points for a low-traffic personal-scale project,
#     not tuned values - adjust based on observed traffic) ---
REQUEST_COUNT_THRESHOLD="${REQUEST_COUNT_THRESHOLD:-100}"       # per 5-min window
ERROR_RATIO_THRESHOLD="${ERROR_RATIO_THRESHOLD:-0.2}"           # 20%
ERROR_RATIO_MIN_REQUESTS="${ERROR_RATIO_MIN_REQUESTS:-5}"       # per 5-min window, volume gate
INSTANCE_COUNT_THRESHOLD="${INSTANCE_COUNT_THRESHOLD:-3}"       # active instances
CPU_UTILIZATION_THRESHOLD="${CPU_UTILIZATION_THRESHOLD:-0.9}"   # 90%
OAUTH_FAILURE_THRESHOLD="${OAUTH_FAILURE_THRESHOLD:-3}"         # per 10-min window

STATE_DIR="$(dirname "$0")/../.private/cloud-monitoring-alerts"
mkdir -p "${STATE_DIR}"

DRY_RUN=0
if [[ "${1:-}" == "--dry-run" ]]; then
  DRY_RUN=1
  shift
fi
SUBCOMMAND="${1:-}"

# Mutating gcloud calls go through this so --dry-run can show intent without
# touching real resources. Read-only lookups (list/describe) bypass this and
# always run, since they're needed to decide create-vs-update and are safe.
run_gcloud() {
  echo "+ gcloud $*" >&2
  if [[ "${DRY_RUN}" == "1" ]]; then
    echo "  (dry-run: not executed)" >&2
    return 0
  fi
  gcloud "$@"
}

# --- 1. Notification channel (idempotent on email_address, not display name) ---
cmd_channel() {
  local existing
  existing=$(gcloud alpha monitoring channels list \
    --project="${PROJECT_ID}" \
    --filter="type=\"email\" AND labels.email_address=\"${ALERT_EMAIL}\"" \
    --format="value(name)")

  if [[ -n "${existing}" ]]; then
    echo "Email channel already exists: ${existing}"
    return 0
  fi

  run_gcloud alpha monitoring channels create \
    --project="${PROJECT_ID}" \
    --display-name="Personal email (${SERVICE_NAME} alerts)" \
    --description="Primary contact for Cloud Run traffic/error/cost/auth alerts on ${SERVICE_NAME}" \
    --type=email \
    --channel-labels="email_address=${ALERT_EMAIL}"
}

# Resolve the channel's resource name (projects/PROJECT/notificationChannels/N).
# Used by each policy subcommand; requires `channel` to have been run first.
resolve_channel_name() {
  gcloud alpha monitoring channels list \
    --project="${PROJECT_ID}" \
    --filter="type=\"email\" AND labels.email_address=\"${ALERT_EMAIL}\"" \
    --format="value(name)"
}

# --- 2. OAuth log-based metric (idempotent create-or-update) ---
LOG_METRIC_NAME="oauth_auth_failures"

cmd_log_metric() {
  local log_filter description
  log_filter="resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"${SERVICE_NAME}\" AND severity>=WARNING AND textPayload=~\"(?i)(oauth|token|auth)\""
  description="Proxy signal for OAuth/auth failures: WARNING+ stderr lines matching oauth|token|auth (case-insensitive regex). NOT a precise per-request failure counter - src/server.py has no dedicated auth-failure logging; this is a coarse signal from the fastmcp library's internal logging. See .agents/skills/cloud-monitoring-alerts/SKILL.md."

  if gcloud logging metrics describe "${LOG_METRIC_NAME}" --project="${PROJECT_ID}" &>/dev/null; then
    run_gcloud logging metrics update "${LOG_METRIC_NAME}" \
      --project="${PROJECT_ID}" \
      --description="${description}" \
      --log-filter="${log_filter}"
  else
    run_gcloud logging metrics create "${LOG_METRIC_NAME}" \
      --project="${PROJECT_ID}" \
      --description="${description}" \
      --log-filter="${log_filter}"
  fi
}

# Create-or-update an alert policy by displayName, from a JSON file.
apply_policy() {
  local display_name="$1" policy_file="$2"
  local existing
  existing=$(gcloud alpha monitoring policies list \
    --project="${PROJECT_ID}" \
    --filter="displayName=\"${display_name}\"" \
    --format="value(name)")

  if [[ -n "${existing}" ]]; then
    run_gcloud alpha monitoring policies update "${existing}" \
      --project="${PROJECT_ID}" \
      --policy-from-file="${policy_file}"
  else
    run_gcloud alpha monitoring policies create \
      --project="${PROJECT_ID}" \
      --policy-from-file="${policy_file}"
  fi
}

# --- 3. Policy: request count spike ---
cmd_policy_request_count() {
  local channel_name display_name policy_file
  channel_name=$(resolve_channel_name)
  : "${channel_name:?Run the 'channel' subcommand first}"
  display_name="${SERVICE_NAME}: request count spike"
  policy_file="${STATE_DIR}/policy-request-count.json"

  cat > "${policy_file}" <<EOF
{
  "displayName": "${display_name}",
  "combiner": "OR",
  "conditions": [
    {
      "displayName": "Request count > ${REQUEST_COUNT_THRESHOLD} per 5 min",
      "conditionThreshold": {
        "filter": "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"${SERVICE_NAME}\" AND metric.type=\"run.googleapis.com/request_count\"",
        "comparison": "COMPARISON_GT",
        "thresholdValue": ${REQUEST_COUNT_THRESHOLD},
        "duration": "0s",
        "aggregations": [
          {
            "alignmentPeriod": "300s",
            "perSeriesAligner": "ALIGN_SUM",
            "crossSeriesReducer": "REDUCE_SUM"
          }
        ],
        "trigger": {"count": 1}
      }
    }
  ],
  "notificationChannels": ["${channel_name}"],
  "documentation": {
    "content": "Request count exceeded ${REQUEST_COUNT_THRESHOLD} in a 5-minute window on ${SERVICE_NAME}. Tunable via REQUEST_COUNT_THRESHOLD in tools/setup-cloud-monitoring-alerts.sh.",
    "mimeType": "text/markdown"
  },
  "alertStrategy": {
    "autoClose": "604800s"
  }
}
EOF

  apply_policy "${display_name}" "${policy_file}"
}

# --- 4. Policy: 5xx error rate increase (MQL ratio + volume gate) ---
cmd_policy_error_rate() {
  local channel_name display_name policy_file mql_query
  channel_name=$(resolve_channel_name)
  : "${channel_name:?Run the 'channel' subcommand first}"
  display_name="${SERVICE_NAME}: 5xx error rate spike"
  policy_file="${STATE_DIR}/policy-error-rate.json"

  # GCP requires policies with a "monitoring_query_language" condition to have
  # exactly one condition - a separate conditionThreshold volume gate can't be
  # combined into the same policy. So the volume gate is folded directly into
  # this MQL query instead (both error_ratio and total request volume are
  # combined into a single boolean condition).
  mql_query=$(cat <<EOF
{
  fetch cloud_run_revision
  | metric 'run.googleapis.com/request_count'
  | filter (resource.service_name == '${SERVICE_NAME}' && metric.response_code_class == '5xx')
  | align delta(5m)
  | every 5m
  | group_by [], [val_5xx: aggregate(value.request_count)]
;
  fetch cloud_run_revision
  | metric 'run.googleapis.com/request_count'
  | filter resource.service_name == '${SERVICE_NAME}'
  | align delta(5m)
  | every 5m
  | group_by [], [val_total: aggregate(value.request_count)]
}
| join
| value [error_ratio: val_5xx / val_total, total: val_total]
| condition error_ratio > ${ERROR_RATIO_THRESHOLD} && total >= ${ERROR_RATIO_MIN_REQUESTS}
EOF
)
  # JSON-escape the MQL query (newlines -> \n, double quotes -> \").
  mql_query=$(printf '%s' "${mql_query}" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')

  cat > "${policy_file}" <<EOF
{
  "displayName": "${display_name}",
  "combiner": "OR",
  "conditions": [
    {
      "displayName": "5xx ratio > ${ERROR_RATIO_THRESHOLD} with volume gate >= ${ERROR_RATIO_MIN_REQUESTS}",
      "conditionMonitoringQueryLanguage": {
        "query": ${mql_query},
        "duration": "0s",
        "trigger": {"count": 1}
      }
    }
  ],
  "notificationChannels": ["${channel_name}"],
  "documentation": {
    "content": "5xx response ratio exceeded ${ERROR_RATIO_THRESHOLD} on ${SERVICE_NAME}, with at least ${ERROR_RATIO_MIN_REQUESTS} requests in the window (volume gate prevents a single failed request from paging). Tunable via ERROR_RATIO_THRESHOLD / ERROR_RATIO_MIN_REQUESTS in tools/setup-cloud-monitoring-alerts.sh.",
    "mimeType": "text/markdown"
  },
  "alertStrategy": {
    "autoClose": "604800s"
  }
}
EOF

  apply_policy "${display_name}" "${policy_file}"
}

# --- 5. Policy: instance count / CPU spike (cost-runaway signal) ---
cmd_policy_instance_cpu() {
  local channel_name display_name policy_file
  channel_name=$(resolve_channel_name)
  : "${channel_name:?Run the 'channel' subcommand first}"
  display_name="${SERVICE_NAME}: instance/CPU spike"
  policy_file="${STATE_DIR}/policy-instance-cpu.json"

  cat > "${policy_file}" <<EOF
{
  "displayName": "${display_name}",
  "combiner": "OR",
  "conditions": [
    {
      "displayName": "Active instance count > ${INSTANCE_COUNT_THRESHOLD} for 3 min",
      "conditionThreshold": {
        "filter": "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"${SERVICE_NAME}\" AND metric.type=\"run.googleapis.com/container/instance_count\" AND metric.labels.state=\"active\"",
        "comparison": "COMPARISON_GT",
        "thresholdValue": ${INSTANCE_COUNT_THRESHOLD},
        "duration": "180s",
        "aggregations": [
          {
            "alignmentPeriod": "180s",
            "perSeriesAligner": "ALIGN_MAX",
            "crossSeriesReducer": "REDUCE_MAX"
          }
        ],
        "trigger": {"count": 1}
      }
    },
    {
      "displayName": "CPU utilization (p99) > ${CPU_UTILIZATION_THRESHOLD} for 3 min",
      "conditionThreshold": {
        "filter": "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"${SERVICE_NAME}\" AND metric.type=\"run.googleapis.com/container/cpu/utilizations\"",
        "comparison": "COMPARISON_GT",
        "thresholdValue": ${CPU_UTILIZATION_THRESHOLD},
        "duration": "180s",
        "aggregations": [
          {
            "alignmentPeriod": "180s",
            "perSeriesAligner": "ALIGN_PERCENTILE_99",
            "crossSeriesReducer": "REDUCE_MAX"
          }
        ],
        "trigger": {"count": 1}
      }
    }
  ],
  "notificationChannels": ["${channel_name}"],
  "documentation": {
    "content": "Active instance count exceeded ${INSTANCE_COUNT_THRESHOLD} or CPU utilization exceeded ${CPU_UTILIZATION_THRESHOLD} for 3+ minutes on ${SERVICE_NAME} (normally idles at 0-1 instances via scale-to-zero) - a cost-runaway signal. Tunable via INSTANCE_COUNT_THRESHOLD / CPU_UTILIZATION_THRESHOLD in tools/setup-cloud-monitoring-alerts.sh.",
    "mimeType": "text/markdown"
  },
  "alertStrategy": {
    "autoClose": "604800s"
  }
}
EOF

  apply_policy "${display_name}" "${policy_file}"
}

# --- 6. Policy: OAuth auth-failure spike (documented proxy signal) ---
cmd_policy_oauth_failures() {
  local channel_name display_name policy_file
  channel_name=$(resolve_channel_name)
  : "${channel_name:?Run the 'channel' subcommand first}"
  display_name="${SERVICE_NAME}: OAuth failure spike (proxy signal)"
  policy_file="${STATE_DIR}/policy-oauth-failures.json"

  cat > "${policy_file}" <<EOF
{
  "displayName": "${display_name}",
  "combiner": "OR",
  "conditions": [
    {
      "displayName": "oauth_auth_failures > ${OAUTH_FAILURE_THRESHOLD} per 10 min",
      "conditionThreshold": {
        "filter": "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"${SERVICE_NAME}\" AND metric.type=\"logging.googleapis.com/user/${LOG_METRIC_NAME}\"",
        "comparison": "COMPARISON_GT",
        "thresholdValue": ${OAUTH_FAILURE_THRESHOLD},
        "duration": "0s",
        "aggregations": [
          {
            "alignmentPeriod": "600s",
            "perSeriesAligner": "ALIGN_SUM",
            "crossSeriesReducer": "REDUCE_SUM"
          }
        ],
        "trigger": {"count": 1}
      }
    }
  ],
  "notificationChannels": ["${channel_name}"],
  "documentation": {
    "content": "PROXY SIGNAL, not a precise auth-failure counter: counts WARNING+ severity log lines on ${SERVICE_NAME} whose text matches oauth|token|auth (case-insensitive). src/server.py has no dedicated per-request auth-failure logging; this proxies off the fastmcp library's internal logging. Exceeded ${OAUTH_FAILURE_THRESHOLD} in a 10-minute window. See .agents/skills/cloud-monitoring-alerts/SKILL.md. Tunable via OAUTH_FAILURE_THRESHOLD in tools/setup-cloud-monitoring-alerts.sh.",
    "mimeType": "text/markdown"
  },
  "alertStrategy": {
    "autoClose": "604800s"
  }
}
EOF

  apply_policy "${display_name}" "${policy_file}"
}

cmd_all() {
  cmd_channel
  cmd_log_metric
  cmd_policy_request_count
  cmd_policy_error_rate
  cmd_policy_instance_cpu
  cmd_policy_oauth_failures
}

usage() {
  sed -n '2,25p' "$0" | sed 's/^# \{0,1\}//'
}

case "${SUBCOMMAND}" in
  channel) cmd_channel ;;
  log-metric) cmd_log_metric ;;
  policy-request-count) cmd_policy_request_count ;;
  policy-error-rate) cmd_policy_error_rate ;;
  policy-instance-cpu) cmd_policy_instance_cpu ;;
  policy-oauth-failures) cmd_policy_oauth_failures ;;
  all) cmd_all ;;
  ""|-h|--help) usage; exit 1 ;;
  *) echo "Unknown subcommand: ${SUBCOMMAND}" >&2; usage; exit 1 ;;
esac
