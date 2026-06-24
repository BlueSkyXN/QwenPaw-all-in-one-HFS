#!/usr/bin/env bash
set -euo pipefail

image="${IMAGE:-qwenpaw-all-in-one-hfs:dev}"
qwenpaw_version="${QWENPAW_VERSION:-1.1.12.post2}"
uv_version="${UV_VERSION:-0.7.20}"
qwenpaw_sha="${QWENPAW_PACKAGE_SHA256:-c07ba7780d0752281138298a6e2a7b0efd372bffab60e68d1d7e9856a5b16e6a}"
qwenpaw_upstream_ref="${QWENPAW_UPSTREAM_REF:-09fc515c88a5e817870e6b975e66b5be81893e03}"

args=(
  --build-arg "QWENPAW_VERSION=${qwenpaw_version}"
  --build-arg "UV_VERSION=${uv_version}"
  --build-arg "QWENPAW_UPSTREAM_REF=${qwenpaw_upstream_ref}"
)

if [ -n "$qwenpaw_sha" ]; then
  args+=(--build-arg "QWENPAW_PACKAGE_SHA256=${qwenpaw_sha}")
fi

docker build -t "$image" "${args[@]}" .
