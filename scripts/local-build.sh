#!/usr/bin/env bash
set -euo pipefail

image="${IMAGE:-qwenpaw-all-in-one-hfs:dev}"
base_image_ref="${BASE_IMAGE_REF:-node:22-slim@sha256:6c74791e557ce11fc957704f6d4fe134a7bc8d6f5ca4403205b2966bd488f6b3}"
qwenpaw_source_repo="${QWENPAW_SOURCE_REPO:-https://github.com/agentscope-ai/QwenPaw.git}"
qwenpaw_source_ref="${QWENPAW_SOURCE_REF:-734c8b9fa610381fa6d79b10ae3641b6db4a8cb2}"
qwenpaw_source_version="${QWENPAW_SOURCE_VERSION:-2.0.1}"
qwenpaw_console_bundle_url="${QWENPAW_CONSOLE_BUNDLE_URL:-https://github.com/BlueSkyXN/QwenPaw-all-in-one-HFS/releases/download/qwenpaw-console-734c8b9f/qwenpaw-console-734c8b9fa610381fa6d79b10ae3641b6db4a8cb2.tar.gz}"
qwenpaw_console_bundle_sha256="${QWENPAW_CONSOLE_BUNDLE_SHA256:-c1bbaa54f7f07411b5948c2984c054c0e20352f46f6406101db65a9188aeb8cf}"
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
