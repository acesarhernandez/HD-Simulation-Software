#!/usr/bin/env bash
set -euo pipefail

# Read-only Zammad audit collector.
# This script only uses HTTP GET calls against the Zammad API.

usage() {
  cat <<USAGE
Usage:
  ./scripts/zammad_readonly_audit.sh --url <https://zammad.example.com> --token <api_token> [--outdir <path>]

Options:
  --url      Base URL of Zammad (example: https://helpdesk.lab.local)
  --token    Zammad API token for an admin user
  --outdir   Output directory for evidence (default: ./audit-output)
  -h, --help Show this help message

Notes:
  - This script is read-only and performs GET requests only.
  - It writes JSON snapshots so you can diff configurations over time.
USAGE
}

ZAMMAD_URL=""
ZAMMAD_TOKEN=""
OUTDIR="./audit-output"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --url)
      ZAMMAD_URL="${2:-}"
      shift 2
      ;;
    --token)
      ZAMMAD_TOKEN="${2:-}"
      shift 2
      ;;
    --outdir)
      OUTDIR="${2:-}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage
      exit 1
      ;;
  esac
done

if [[ -z "$ZAMMAD_URL" || -z "$ZAMMAD_TOKEN" ]]; then
  echo "Error: --url and --token are required." >&2
  usage
  exit 1
fi

if ! command -v curl >/dev/null 2>&1; then
  echo "Error: curl is required but not installed." >&2
  exit 1
fi

HAS_JQ=0
if command -v jq >/dev/null 2>&1; then
  HAS_JQ=1
fi

ZAMMAD_URL="${ZAMMAD_URL%/}"
TS="$(date +%Y%m%d-%H%M%S)"
RUN_DIR="${OUTDIR%/}/zammad-audit-${TS}"
RAW_DIR="$RUN_DIR/raw"
mkdir -p "$RAW_DIR"

ENDPOINTS=(
  "users/me"
  "groups"
  "roles"
  "slas"
  "triggers"
  "overviews"
  "ticket_priorities"
  "ticket_states"
  "object_manager_attributes"
  "core_workflows"
  "channels_email"
)

fetch_endpoint() {
  local endpoint="$1"
  local safe_name
  safe_name="$(echo "$endpoint" | tr '/?' '__')"
  local body_file="$RAW_DIR/${safe_name}.json"
  local code_file="$RAW_DIR/${safe_name}.status"

  local tmp_file
  tmp_file="$(mktemp)"

  local http_code
  http_code="$({
    curl -sS \
      -H "Authorization: Token token=$ZAMMAD_TOKEN" \
      -H "Content-Type: application/json" \
      -o "$tmp_file" \
      -w "%{http_code}" \
      "$ZAMMAD_URL/api/v1/$endpoint"
  })"

  mv "$tmp_file" "$body_file"
  echo "$http_code" > "$code_file"

  if [[ "$http_code" =~ ^2 ]]; then
    echo "OK   $endpoint ($http_code)"
  else
    echo "WARN $endpoint ($http_code)"
  fi
}

SUMMARY_FILE="$RUN_DIR/summary.md"
{
  echo "# Zammad Read-Only Audit Summary"
  echo
  echo "- Timestamp: $(date)"
  echo "- Base URL: $ZAMMAD_URL"
  echo "- Output path: $RUN_DIR"
  echo
} > "$SUMMARY_FILE"

echo "Collecting configuration snapshots..."
for endpoint in "${ENDPOINTS[@]}"; do
  fetch_endpoint "$endpoint"
done

echo >> "$SUMMARY_FILE"
echo "## Endpoint Status" >> "$SUMMARY_FILE"
for endpoint in "${ENDPOINTS[@]}"; do
  safe_name="$(echo "$endpoint" | tr '/?' '__')"
  code="$(cat "$RAW_DIR/${safe_name}.status")"
  echo "- $endpoint: HTTP $code" >> "$SUMMARY_FILE"
done

if [[ "$HAS_JQ" -eq 1 ]]; then
  echo >> "$SUMMARY_FILE"
  echo "## Quick Parsed Checks" >> "$SUMMARY_FILE"

  groups_count=$(jq 'if type=="array" then length else 0 end' "$RAW_DIR/groups.json" 2>/dev/null || echo 0)
  roles_count=$(jq 'if type=="array" then length else 0 end' "$RAW_DIR/roles.json" 2>/dev/null || echo 0)
  slas_count=$(jq 'if type=="array" then length else 0 end' "$RAW_DIR/slas.json" 2>/dev/null || echo 0)
  triggers_count=$(jq 'if type=="array" then length else 0 end' "$RAW_DIR/triggers.json" 2>/dev/null || echo 0)
  overviews_count=$(jq 'if type=="array" then length else 0 end' "$RAW_DIR/overviews.json" 2>/dev/null || echo 0)
  cw_count=$(jq 'if type=="array" then length else 0 end' "$RAW_DIR/core_workflows.json" 2>/dev/null || echo 0)

  echo "- Groups found: $groups_count" >> "$SUMMARY_FILE"
  echo "- Roles found: $roles_count" >> "$SUMMARY_FILE"
  echo "- SLAs found: $slas_count" >> "$SUMMARY_FILE"
  echo "- Triggers found: $triggers_count" >> "$SUMMARY_FILE"
  echo "- Overviews found: $overviews_count" >> "$SUMMARY_FILE"
  echo "- Core workflows found: $cw_count" >> "$SUMMARY_FILE"

  support_level_exists=$(jq '[.[]? | select(.name=="support_level")] | length' "$RAW_DIR/object_manager_attributes.json" 2>/dev/null || echo 0)
  if [[ "$support_level_exists" -gt 0 ]]; then
    echo "- Support Level field: FOUND" >> "$SUMMARY_FILE"
  else
    echo "- Support Level field: NOT FOUND" >> "$SUMMARY_FILE"
  fi

  sla_breach_trigger=$(jq '[.[]? | select((.name // "") | test("SLA"; "i") and (.condition // "" | tostring | test("escalation"; "i")))] | length' "$RAW_DIR/triggers.json" 2>/dev/null || echo 0)
  echo "- SLA-related triggers detected (heuristic): $sla_breach_trigger" >> "$SUMMARY_FILE"

  echo >> "$SUMMARY_FILE"
  echo "## Priority Names" >> "$SUMMARY_FILE"
  jq -r '.[]? | "- \(.id): \(.name)"' "$RAW_DIR/ticket_priorities.json" >> "$SUMMARY_FILE" 2>/dev/null || true

  echo >> "$SUMMARY_FILE"
  echo "## SLA Names" >> "$SUMMARY_FILE"
  jq -r '.[]? | "- \(.id): \(.name)"' "$RAW_DIR/slas.json" >> "$SUMMARY_FILE" 2>/dev/null || true

  echo >> "$SUMMARY_FILE"
  echo "## Trigger Names" >> "$SUMMARY_FILE"
  jq -r '.[]? | "- \(.id): \(.name)"' "$RAW_DIR/triggers.json" >> "$SUMMARY_FILE" 2>/dev/null || true

  echo >> "$SUMMARY_FILE"
  echo "## Overview Names" >> "$SUMMARY_FILE"
  jq -r '.[]? | "- \(.id): \(.name)"' "$RAW_DIR/overviews.json" >> "$SUMMARY_FILE" 2>/dev/null || true
else
  echo >> "$SUMMARY_FILE"
  echo "## Quick Parsed Checks" >> "$SUMMARY_FILE"
  echo "- jq not installed; raw JSON snapshots collected only." >> "$SUMMARY_FILE"
fi

echo ""
echo "Audit complete."
echo "Summary: $SUMMARY_FILE"
echo "Raw JSON: $RAW_DIR"
