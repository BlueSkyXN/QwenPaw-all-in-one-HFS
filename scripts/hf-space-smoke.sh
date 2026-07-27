#!/usr/bin/env bash
set -euo pipefail

base="${1:?usage: $0 https://your-space.hf.space}"
base="${base%/}"
ops_token="${OPS_TOKEN:-${QWENPAW_OPS_TOKEN:-}}"
admin_token="${ADMIN_TOKEN:-${QWENPAW_ADMIN_TOKEN:-}}"
admin_expected="${SMOKE_ADMIN_ENABLED:-${ADMIN_ENABLED:-false}}"
expected_source_ref="${EXPECTED_QWENPAW_SOURCE_REF:-}"
expected_source_version="${EXPECTED_QWENPAW_SOURCE_VERSION:-}"
expected_console_sha256="${EXPECTED_QWENPAW_CONSOLE_BUNDLE_SHA256:-}"

if [ -n "$expected_source_ref" ] && [[ ! "$expected_source_ref" =~ ^[0-9a-f]{40}$ ]]; then
  printf 'FAIL smoke: EXPECTED_QWENPAW_SOURCE_REF must be a lowercase full Git SHA\n' >&2
  exit 2
fi
if [ -n "$expected_console_sha256" ] && [[ ! "$expected_console_sha256" =~ ^[0-9a-f]{64}$ ]]; then
  printf 'FAIL smoke: EXPECTED_QWENPAW_CONSOLE_BUNDLE_SHA256 must be a lowercase SHA-256 digest\n' >&2
  exit 2
fi

check() {
  local name=$1
  local url=$2
  shift 2
  curl -fsS --max-time 20 "$@" "$url" >/dev/null
  printf 'PASS smoke: %s\n' "$name"
}

check nginx-health "$base/nginx-health"
check healthz "$base/healthz"
check readyz "$base/readyz"
check web-root "$base/"

auth_status_json=$(curl -fsS --max-time 20 "$base/api/auth/status")
read -r auth_enabled auth_has_users < <(
  printf '%s' "$auth_status_json" | python3 -c '
import json
import sys

payload = json.load(sys.stdin)
print(str(bool(payload.get("enabled"))).lower(), str(bool(payload.get("has_users"))).lower())
'
)
if [ "$auth_enabled" = "true" ] && [ "$auth_has_users" = "true" ]; then
  qwenpaw_auth_status=$(curl -sS -o /dev/null -w "%{http_code}" --max-time 20 "$base/api/agents" || true)
  if [ "$qwenpaw_auth_status" != "401" ]; then
    printf 'FAIL smoke: expected protected QwenPaw API status=401 without token, got %s\n' "$qwenpaw_auth_status" >&2
    exit 1
  fi
  printf 'PASS smoke: qwenpaw-auth-boundary status=%s\n' "$qwenpaw_auth_status"
else
  printf 'WARN smoke: QwenPaw auth boundary check skipped; enabled=%s has_users=%s\n' "$auth_enabled" "$auth_has_users" >&2
fi

if [ -n "$ops_token" ]; then
  check ops-health "$base/_ops/health" -H "X-Ops-Token: $ops_token"
  check ops-readyz "$base/_ops/readyz" -H "X-Ops-Token: $ops_token"
  check ops-status "$base/_ops/status" -H "X-Ops-Token: $ops_token"
  check ops-config "$base/_ops/config" -H "X-Ops-Token: $ops_token"
  check ops-persistence "$base/_ops/persistence" -H "X-Ops-Token: $ops_token"
  version_json=$(curl -fsS --max-time 20 -H "X-Ops-Token: $ops_token" "$base/_ops/version")
  EXPECTED_SOURCE_REF="$expected_source_ref" \
  EXPECTED_SOURCE_VERSION="$expected_source_version" \
  EXPECTED_CONSOLE_SHA256="$expected_console_sha256" \
    python3 -c '
import json
import os
import sys

pins = json.load(sys.stdin).get("release_pins", {})
expected = {
    "QWENPAW_SOURCE_REF": os.environ["EXPECTED_SOURCE_REF"],
    "QWENPAW_SOURCE_VERSION": os.environ["EXPECTED_SOURCE_VERSION"],
    "QWENPAW_CONSOLE_BUNDLE_SHA256": os.environ["EXPECTED_CONSOLE_SHA256"],
}
for key, value in expected.items():
    if value and pins.get(key) != value:
        raise SystemExit(f"{key} mismatch: expected={value!r} actual={pins.get(key)!r}")
source_ref = pins.get("QWENPAW_SOURCE_REF", "")
bundle_url = pins.get("QWENPAW_CONSOLE_BUNDLE_URL", "")
if source_ref not in bundle_url:
    raise SystemExit("console bundle provenance does not contain the runtime source SHA")
' <<<"$version_json"
  printf 'PASS smoke: ops-version provenance\n'
else
  printf 'WARN smoke: OPS_TOKEN not set; protected /_ops checks skipped\n' >&2
fi

admin_status=$(curl -sS -o /dev/null -w "%{http_code}" --max-time 10 "$base/_admin/" || true)
if [ "$admin_expected" = "true" ]; then
  if [ -z "$admin_token" ]; then
    printf 'FAIL smoke: ADMIN_TOKEN is required when SMOKE_ADMIN_ENABLED=true\n' >&2
    exit 1
  fi
  if [ "$admin_status" != "200" ]; then
    printf 'FAIL smoke: expected _admin status=200 when enabled, got %s\n' "$admin_status" >&2
    exit 1
  fi
  printf 'PASS smoke: admin root status=%s\n' "$admin_status"
  check admin-status "$base/_admin/api/status" -H "X-Admin-Token: $admin_token"
  check admin-actions "$base/_admin/api/actions" -H "X-Admin-Token: $admin_token"
  check admin-audit "$base/_admin/api/audit?limit=5" -H "X-Admin-Token: $admin_token"
else
  case "$admin_status" in
    401|403|404)
      printf 'PASS smoke: admin default boundary status=%s\n' "$admin_status"
      ;;
    *)
      printf 'FAIL smoke: unexpected _admin status=%s\n' "$admin_status" >&2
      exit 1
      ;;
  esac
fi

printf 'PASS qwenpaw-hfs-smoke\n'
