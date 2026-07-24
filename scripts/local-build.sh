#!/usr/bin/env bash
set -euo pipefail

image="${IMAGE:-qwenpaw-all-in-one-hfs:dev}"
base_image_ref="${BASE_IMAGE_REF:-node:22-slim@sha256:6c74791e557ce11fc957704f6d4fe134a7bc8d6f5ca4403205b2966bd488f6b3}"
qwenpaw_source_repo="${QWENPAW_SOURCE_REPO:-https://github.com/agentscope-ai/QwenPaw.git}"
qwenpaw_source_ref="${QWENPAW_SOURCE_REF:-ab814123c59f18b6045ff0204bf2ec5fb31fd598}"
qwenpaw_source_version="${QWENPAW_SOURCE_VERSION:-2.0.1}"
qwenpaw_console_bundle_url="${QWENPAW_CONSOLE_BUNDLE_URL:-https://github.com/BlueSkyXN/QwenPaw-all-in-one-HFS/releases/download/qwenpaw-console-ab814123/qwenpaw-console-ab814123c59f18b6045ff0204bf2ec5fb31fd598.tar.gz}"
qwenpaw_console_bundle_sha256="${QWENPAW_CONSOLE_BUNDLE_SHA256:-ce5cc067101ea505ce89664d15a1b757124eeac22a04b273ccc7c016d7b22c66}"
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
