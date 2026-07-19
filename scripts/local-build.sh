#!/usr/bin/env bash
set -euo pipefail

image="${IMAGE:-qwenpaw-all-in-one-hfs:dev}"
base_image_ref="${BASE_IMAGE_REF:-node:22-slim@sha256:6c74791e557ce11fc957704f6d4fe134a7bc8d6f5ca4403205b2966bd488f6b3}"
qwenpaw_source_repo="${QWENPAW_SOURCE_REPO:-https://github.com/agentscope-ai/QwenPaw.git}"
qwenpaw_source_ref="${QWENPAW_SOURCE_REF:-a15a69fca73e67c17dc47326e933eaa259fa0d8d}"
qwenpaw_source_version="${QWENPAW_SOURCE_VERSION:-2.0.0.post3}"
uv_version="${UV_VERSION:-0.7.20}"

args=(
  --build-arg "BASE_IMAGE_REF=${base_image_ref}"
  --build-arg "QWENPAW_SOURCE_REPO=${qwenpaw_source_repo}"
  --build-arg "QWENPAW_SOURCE_REF=${qwenpaw_source_ref}"
  --build-arg "QWENPAW_SOURCE_VERSION=${qwenpaw_source_version}"
  --build-arg "UV_VERSION=${uv_version}"
)

docker build -t "$image" "${args[@]}" .
