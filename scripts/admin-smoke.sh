#!/usr/bin/env bash
set -euo pipefail

base="${1:?usage: $0 https://your-space.hf.space}"
base="${base%/}"
admin_expected="${ADMIN_EXPECTED_ENABLED:-${ADMIN_ENABLED:-false}}"
admin_actions="${ADMIN_SMOKE_ACTIONS:-false}"
admin_token="${ADMIN_TOKEN:-${QWENPAW_ADMIN_TOKEN:-}}"
admin_csrf="${ADMIN_CSRF_TOKEN:-${QWENPAW_ADMIN_CSRF_TOKEN:-}}"

expect_status() {
  local name=$1
  local expected=$2
  shift 2
  local status
  status=$(curl -sS -o /dev/null -w "%{http_code}" --max-time 15 "$@" || true)
  if [ "$status" != "$expected" ]; then
    printf 'FAIL admin-smoke: %s expected=%s got=%s\n' "$name" "$expected" "$status" >&2
    exit 1
  fi
  printf 'PASS admin-smoke: %s status=%s\n' "$name" "$status"
}

require_admin_token() {
  if [ -n "$admin_token" ]; then
    return
  fi
  printf 'FAIL admin-smoke: ADMIN_TOKEN is required when ADMIN_EXPECTED_ENABLED=true\n' >&2
  exit 1
}

require_admin_csrf() {
  if [ -n "$admin_csrf" ]; then
    return
  fi
  printf 'FAIL admin-smoke: ADMIN_CSRF_TOKEN is required for mutating admin checks\n' >&2
  exit 1
}

if [ "$admin_expected" != "true" ]; then
  expect_status "disabled-root" "404" "$base/_admin/"
  expect_status "disabled-status" "404" "$base/_admin/api/status"
  printf 'PASS qwenpaw-admin-smoke\n'
  exit 0
fi

require_admin_token

expect_status "root" "200" "$base/_admin/"
expect_status "status-unauthorized" "401" "$base/_admin/api/status"
expect_status "status-bad-token" "401" -H "X-Admin-Token: invalid-admin-token" "$base/_admin/api/status"
expect_status "status" "200" -H "X-Admin-Token: $admin_token" "$base/_admin/api/status"
expect_status "actions" "200" -H "X-Admin-Token: $admin_token" "$base/_admin/api/actions"
expect_status "audit" "200" -H "X-Admin-Token: $admin_token" "$base/_admin/api/audit?limit=5"
expect_status "action-missing-csrf" "403" \
  -H "X-Admin-Token: $admin_token" \
  -H "Content-Type: application/json" \
  -d '{"confirm":true}' \
  "$base/_admin/api/actions/run-health-checks"

require_admin_csrf

expect_status "action-missing-confirm" "400" \
  -H "X-Admin-Token: $admin_token" \
  -H "X-CSRF-Token: $admin_csrf" \
  -H "Content-Type: application/json" \
  -d '{}' \
  "$base/_admin/api/actions/run-health-checks"

if [ "$admin_actions" = "true" ]; then
  expect_status "run-health-checks" "200" \
    -H "X-Admin-Token: $admin_token" \
    -H "X-CSRF-Token: $admin_csrf" \
    -H "Content-Type: application/json" \
    -d '{"confirm":true}' \
    "$base/_admin/api/actions/run-health-checks"
else
  printf 'SKIP admin-smoke: run-health-checks requires ADMIN_SMOKE_ACTIONS=true\n'
fi

printf 'PASS qwenpaw-admin-smoke\n'
