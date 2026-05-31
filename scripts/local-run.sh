#!/usr/bin/env bash
set -euo pipefail

image="${IMAGE:-qwenpaw-all-in-one-hfs:dev}"
name="${CONTAINER_NAME:-qwenpaw-hfs}"
ops_token="${OPS_TOKEN:-dev-ops-token}"

if docker ps -a --format '{{.Names}}' | grep -qx "$name"; then
  docker rm -f "$name" >/dev/null
fi

docker run --rm -it \
  --name "$name" \
  -p 7860:7860 \
  -v qwenpaw-hfs-data:/data \
  -e OPS_TOKEN="$ops_token" \
  -e QWENPAW_AUTH_ENABLED="${QWENPAW_AUTH_ENABLED:-true}" \
  -e ADMIN_ENABLED="${ADMIN_ENABLED:-false}" \
  "$image"
