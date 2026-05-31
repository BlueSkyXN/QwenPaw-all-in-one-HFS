#!/usr/bin/env bash
set -euo pipefail

image="${IMAGE:-qwenpaw-all-in-one-hfs:dev}"
qwenpaw_version="${QWENPAW_VERSION:-1.1.9}"
uv_version="${UV_VERSION:-0.7.20}"
qwenpaw_sha="${QWENPAW_PACKAGE_SHA256:-73ff2ca8b22dbfd6d233b678fb1de040bb41a1bff8b2b4091ecde866e1e57f63}"
qwenpaw_upstream_ref="${QWENPAW_UPSTREAM_REF:-2d9527bb097f9b09428190f80e1f3fd44f2ff453}"

args=(
  --build-arg "QWENPAW_VERSION=${qwenpaw_version}"
  --build-arg "UV_VERSION=${uv_version}"
  --build-arg "QWENPAW_UPSTREAM_REF=${qwenpaw_upstream_ref}"
)

if [ -n "$qwenpaw_sha" ]; then
  args+=(--build-arg "QWENPAW_PACKAGE_SHA256=${qwenpaw_sha}")
fi

docker build -t "$image" "${args[@]}" .
