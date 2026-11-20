#!/usr/bin/env bash
set -euo pipefail

image="${IMAGE:-qwenpaw-all-in-one-hfs:dev}"
base_image_ref="${BASE_IMAGE_REF:-node:22-slim@sha256:6c74791e557ce11fc957704f6d4fe134a7bc8d6f5ca4403205b2966bd488f6b3}"
qwenpaw_source_repo="${QWENPAW_SOURCE_REPO:-https://github.com/agentscope-ai/QwenPaw.git}"
qwenpaw_source_ref="${QWENPAW_SOURCE_REF:-ee58cb1a64f2b21e825c525f73dc44bc7941edea}"
qwenpaw_source_version="${QWENPAW_SOURCE_VERSION:-2.3.0.post1}"
qwenpaw_console_bundle_url="${QWENPAW_CONSOLE_BUNDLE_URL:-https://github.com/BlueSkyXN/QwenPaw-all-in-one-HFS/releases/download/qwenpaw-console-ee58cb1a/qwenpaw-console-ee58cb1a64f2b21e825c525f73dc44bc7941edea.tar.gz}"
qwenpaw_console_bundle_sha256="${QWENPAW_CONSOLE_BUNDLE_SHA256:-d90b222a2390b277c70bbbc5f49cd7050e336d160d0a7ab5af248abd1f08b50e}"
uv_version="${UV_VERSION:-0.7.20}"

args=(
  --build-arg "BASE_IMAGE_REF=${base_image_ref}"
  --build-arg "QWENPAW_SOURCE_REPO=${qwenpaw_source_repo}"
  --build-arg "QWENPAW_SOURCE_REF=${qwenpaw_source_ref}"
  --build-arg "QWENPAW_SOURCE_VERSION=${qwenpaw_source_version}"
  --build-arg "QWENPAW_CONSOLE_BUNDLE_URL=${qwenpaw_console_bundle_url}"
  --build-arg "QWENPAW_CONSOLE_BUNDLE_SHA256=${qwenpaw_console_bundle_sha256}"
  --build-arg "UV_VERSION=${uv_version}"
)

docker build -t "$image" "${args[@]}" .
