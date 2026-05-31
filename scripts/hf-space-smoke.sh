#!/usr/bin/env bash
set -euo pipefail

base="${1:?usage: $0 https://your-space.hf.space}"
base="${base%/}"
ops_token="${OPS_TOKEN:-${QWENPAW_OPS_TOKEN:-}}"

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

if [ -n "$ops_token" ]; then
  check ops-health "$base/_ops/health" -H "X-Ops-Token: $ops_token"
  check ops-status "$base/_ops/status" -H "X-Ops-Token: $ops_token"
  check ops-config "$base/_ops/config" -H "X-Ops-Token: $ops_token"
else
  printf 'WARN smoke: OPS_TOKEN not set; protected /_ops checks skipped\n' >&2
fi

admin_status=$(curl -sS -o /dev/null -w "%{http_code}" --max-time 10 "$base/_admin/" || true)
case "$admin_status" in
  401|403|404)
    printf 'PASS smoke: admin default boundary status=%s\n' "$admin_status"
    ;;
  *)
    printf 'FAIL smoke: unexpected _admin status=%s\n' "$admin_status" >&2
    exit 1
    ;;
esac

printf 'PASS qwenpaw-hfs-smoke\n'
