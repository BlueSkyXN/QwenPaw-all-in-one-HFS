#!/usr/bin/env bash
set -euo pipefail

image="${IMAGE:-qwenpaw-all-in-one-hfs:dev}"
qwenpaw_source_repo="${QWENPAW_SOURCE_REPO:-https://github.com/agentscope-ai/QwenPaw.git}"
qwenpaw_source_ref="${QWENPAW_SOURCE_REF:-25015cb5e36fc7a4067d19c6d11ced2c1fe1f4e0}"
qwenpaw_source_version="${QWENPAW_SOURCE_VERSION:-2.0.0b1}"
uv_version="${UV_VERSION:-0.7.20}"

args=(
  --build-arg "QWENPAW_SOURCE_REPO=${qwenpaw_source_repo}"
  --build-arg "QWENPAW_SOURCE_REF=${qwenpaw_source_ref}"
  --build-arg "QWENPAW_SOURCE_VERSION=${qwenpaw_source_version}"
  --build-arg "UV_VERSION=${uv_version}"
)

docker build -t "$image" "${args[@]}" .
