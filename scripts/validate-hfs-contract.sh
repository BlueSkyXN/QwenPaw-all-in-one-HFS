#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$repo_root"

errors=0

fail() {
  printf 'FAIL hfs-contract: %s\n' "$1" >&2
  errors=$((errors + 1))
}

require_file() {
  local path=$1
  if [ ! -f "$path" ]; then
    fail "missing required file: $path"
  fi
}

require_path() {
  local path=$1
  if [ ! -e "$path" ]; then
    fail "missing required path: $path"
  fi
}

require_grep() {
  local pattern=$1
  local path=$2
  local message=$3
  if ! grep -Eq "$pattern" "$path"; then
    fail "$message"
  fi
}

require_absent() {
  local pattern=$1
  local path=$2
  local message=$3
  if grep -Eq "$pattern" "$path"; then
    fail "$message"
  fi
}

frontmatter_value() {
  local key=$1
  awk -v key="$key" '
    NR == 1 && $0 == "---" { in_yaml = 1; next }
    in_yaml && $0 == "---" { exit }
    in_yaml {
      split($0, parts, ":")
      if (parts[1] == key) {
        sub("^[^:]+:[[:space:]]*", "", $0)
        print $0
      }
    }
  ' README.md | tail -n 1
}

require_file README.md
require_file Dockerfile
require_file hfs-dev.toml
require_file AGENTS.md
require_path docker
require_file docker/nginx.conf
require_file docker/entrypoint.sh
require_file docker/supervisord.conf
require_file docker/prepare_runtime_config.py
require_file docker/ops_service.py
require_file docker/admin_service.py
require_file docker/healthcheck.sh
require_file scripts/admin-smoke.sh
require_file scripts/check-qwenpaw-pins.py
require_file scripts/hf-space-smoke.sh
require_file docs/hfs-alignment.md

python3 - "$repo_root" <<'PY_VALIDATE_HFS'
from __future__ import annotations

import sys
import tomllib
from pathlib import Path

root = Path(sys.argv[1])
manifest = tomllib.loads((root / "hfs-dev.toml").read_text(encoding="utf-8"))

expected = {
    "schema_version": 2,
    "standard": "hfs-dev",
    "pattern": "A",
    "runtime_mode": "source-fetch",
    "space_root_mode": "repo-root",
    "hfs_dir": ".",
    "public_port": 7860,
    "release_pin_required": True,
}

failures: list[str] = []
for key, value in expected.items():
    if manifest.get(key) != value:
        failures.append(f"hfs-dev.toml {key} must be {value!r}, got {manifest.get(key)!r}")

if "release_pin_surfaces" in manifest:
    failures.append("hfs-dev.toml v2 must use structured [[release_pins]], not release_pin_surfaces")

release_pins = manifest.get("release_pins")
expected_pins = {
    "BASE_IMAGE_REF": {"type": "image_ref", "required_for_release": True, "dev_mutable_default_allowed": True, "release_requires_digest": True},
    "QWENPAW_SOURCE_REPO": {"type": "metadata", "required_for_release": True, "dev_mutable_default_allowed": True},
    "QWENPAW_SOURCE_REF": {"type": "git_ref", "required_for_release": True, "dev_mutable_default_allowed": True, "release_requires_commit_sha": True},
    "QWENPAW_SOURCE_VERSION": {"type": "package_version", "required_for_release": True, "dev_mutable_default_allowed": False},
    "QWENPAW_CONSOLE_BUNDLE_URL": {"type": "artifact", "required_for_release": True, "dev_mutable_default_allowed": True, "release_requires_checksum": True},
    "QWENPAW_CONSOLE_BUNDLE_SHA256": {"type": "checksum", "required_for_release": True, "dev_mutable_default_allowed": False},
    "UV_VERSION": {"type": "package_version", "required_for_release": True, "dev_mutable_default_allowed": True},
}

if not isinstance(release_pins, list) or not release_pins:
    failures.append("hfs-dev.toml release_pins must be a non-empty structured array")
else:
    pins_by_name: dict[str, dict[str, object]] = {}
    for index, pin in enumerate(release_pins, start=1):
        if not isinstance(pin, dict):
            failures.append(f"hfs-dev.toml release_pins[{index}] must be a table")
            continue
        name = pin.get("name")
        if not isinstance(name, str) or not name:
            failures.append(f"hfs-dev.toml release_pins[{index}] must set name")
            continue
        if name in pins_by_name:
            failures.append(f"hfs-dev.toml release_pins duplicate name: {name}")
        pins_by_name[name] = pin

    missing_pins = sorted(set(expected_pins) - set(pins_by_name))
    if missing_pins:
        failures.append("hfs-dev.toml release_pins missing: " + ", ".join(missing_pins))
    unexpected_pins = sorted(set(pins_by_name) - set(expected_pins))
    if unexpected_pins:
        failures.append("hfs-dev.toml release_pins unexpected: " + ", ".join(unexpected_pins))

    for name, expected_pin in expected_pins.items():
        pin = pins_by_name.get(name)
        if not pin:
            continue
        if not isinstance(pin.get("source"), str) or not pin.get("source"):
            failures.append(f"hfs-dev.toml release_pins {name} must set source")
        for key, value in expected_pin.items():
            if pin.get(key) != value:
                failures.append(f"hfs-dev.toml release_pins {name}.{key} must be {value!r}, got {pin.get(key)!r}")

required_files = manifest.get("required_files")
if not isinstance(required_files, list) or not required_files:
    failures.append("hfs-dev.toml required_files must be a non-empty list")
else:
    for rel_path in required_files:
        if not isinstance(rel_path, str) or not (root / rel_path).exists():
            failures.append(f"hfs-dev.toml required file is missing: {rel_path!r}")

if failures:
    for failure in failures:
        print(f"FAIL hfs-contract: {failure}", file=sys.stderr)
    raise SystemExit(1)
PY_VALIDATE_HFS

sdk=$(frontmatter_value sdk)
app_port=$(frontmatter_value app_port)
if [ "$sdk" != "docker" ]; then
  fail "README.md frontmatter must set sdk: docker"
fi
if [ -z "$app_port" ]; then
  fail "README.md frontmatter must set app_port"
fi

docker_expose=$(awk 'toupper($1) == "EXPOSE" { print $2; exit }' Dockerfile)
nginx_listen=$(awk '
  $1 == "listen" {
    value = $2
    gsub(";", "", value)
    split(value, parts, ":")
    print parts[length(parts)]
    exit
  }
' docker/nginx.conf)

if [ -n "$app_port" ] && [ "$docker_expose" != "$app_port" ]; then
  fail "Dockerfile EXPOSE ($docker_expose) must match README.md app_port ($app_port)"
fi
if [ -n "$app_port" ] && [ "$nginx_listen" != "$app_port" ]; then
  fail "docker/nginx.conf listen ($nginx_listen) must match README.md app_port ($app_port)"
fi

if [ -f cloud/hfs/README.md ] || [ -f cloud/hfs/Dockerfile ]; then
  fail "Pattern A repo must keep Space root at repo root, not cloud/hfs/"
fi

require_grep 'Pattern A: HFS Port Repository' docs/hfs-alignment.md "docs/hfs-alignment.md must declare Pattern A"
require_grep 'Runtime mode: source-fetch' docs/hfs-alignment.md "docs/hfs-alignment.md must declare source-fetch runtime mode"
require_grep 'Space root: repo root' docs/hfs-alignment.md "docs/hfs-alignment.md must declare repo root as Space root"

require_grep '^ARG BASE_IMAGE_REF=' Dockerfile "Dockerfile must expose BASE_IMAGE_REF build input"
require_grep '^ARG QWENPAW_SOURCE_REPO=' Dockerfile "Dockerfile must expose QWENPAW_SOURCE_REPO build input"
require_grep '^ARG QWENPAW_SOURCE_REF=' Dockerfile "Dockerfile must expose QWENPAW_SOURCE_REF build input"
require_grep '^ARG QWENPAW_SOURCE_VERSION=' Dockerfile "Dockerfile must expose QWENPAW_SOURCE_VERSION build input"
require_grep '^ARG QWENPAW_CONSOLE_BUNDLE_URL=' Dockerfile "Dockerfile must expose the console bundle artifact input"
require_grep '^ARG QWENPAW_CONSOLE_BUNDLE_SHA256=[0-9a-f]{64}$' Dockerfile "Dockerfile must pin the console bundle checksum"
require_grep '^ARG UV_VERSION=' Dockerfile "Dockerfile must expose UV_VERSION build input"
require_grep '^FROM \${BASE_IMAGE_REF} AS runtime$' Dockerfile "Dockerfile must select base runtime image from BASE_IMAGE_REF"
require_grep '^ARG BASE_IMAGE_REF=node:22-slim@sha256:[0-9a-f]{64}$' Dockerfile "Dockerfile release default must pin the base image by digest"
require_grep 'QWENPAW_SOURCE_REPO=https://github\.com/agentscope-ai/QwenPaw\.git' Dockerfile "Dockerfile must default to the upstream QwenPaw source repository"
require_grep 'QWENPAW_SOURCE_REF=734c8b9fa610381fa6d79b10ae3641b6db4a8cb2' Dockerfile "Dockerfile must default to the requested upstream source commit"
require_grep 'QWENPAW_SOURCE_VERSION=2\.0\.1' Dockerfile "Dockerfile must default to the requested upstream source version"
require_grep 'QWENPAW_CONSOLE_BUNDLE_URL=.*734c8b9fa610381fa6d79b10ae3641b6db4a8cb2' Dockerfile "console artifact must identify the pinned upstream source commit"
require_grep 'git fetch --depth 1 origin "\${QWENPAW_SOURCE_REF}"' Dockerfile "Dockerfile must fetch the pinned upstream source ref"
require_grep 'src/qwenpaw/__version__\.py' Dockerfile "Dockerfile must validate the upstream source version"
require_grep 'sha256sum -c -' Dockerfile "Dockerfile must verify the console artifact before extraction"
require_grep 'tar -xzf /tmp/qwenpaw-console\.tar\.gz -C src/qwenpaw/console' Dockerfile "Dockerfile must extract verified console assets into the Python package source"
require_grep 'test -f src/qwenpaw/console/index\.html' Dockerfile "Dockerfile must require the console entrypoint"
require_absent 'npm ci --include=dev' Dockerfile "HFS worker must not rebuild the memory-heavy upstream console"
require_grep '/tmp/qwenpaw-src' Dockerfile "Dockerfile must install QwenPaw from fetched source"
require_absent 'qwenpaw==\${QWENPAW_VERSION}' Dockerfile "Dockerfile must not install QwenPaw from PyPI package version in source-fetch mode"
require_absent '^ARG QWENPAW_PACKAGE_SHA256=' Dockerfile "Dockerfile must not expose PyPI artifact checksum in source-fetch mode"
require_grep 'fetch_source_ref' scripts/check-qwenpaw-pins.py "pin checker must fetch and validate the upstream source ref"
require_grep 'QWENPAW_SOURCE_VERSION matches upstream source' scripts/check-qwenpaw-pins.py "pin checker must validate upstream source version"
require_grep 'QWENPAW_CONSOLE_BUNDLE_SHA256 matches downloaded artifact' scripts/check-qwenpaw-pins.py "pin checker must validate the console artifact checksum"
require_grep 'require-upstream-main' scripts/check-qwenpaw-pins.py "pin checker must support enforcing current upstream main"

require_absent '^ARG DIFY_' Dockerfile "QwenPaw HFS must not expose Dify image selectors"
require_absent '^FROM \${DIFY_' Dockerfile "QwenPaw HFS must not select Dify images"

require_grep '^local/$|^\*\*/local/$' .dockerignore ".dockerignore must exclude local/ from Docker build context"
require_grep '^\.env\.local$' .dockerignore ".dockerignore must exclude .env.local"
require_grep '^\*\.secret$' .dockerignore ".dockerignore must exclude *.secret"
require_grep '^\*\.key$' .dockerignore ".dockerignore must exclude *.key"
require_grep '^\*\.pem$' .dockerignore ".dockerignore must exclude *.pem"

require_grep '/nginx-health' scripts/hf-space-smoke.sh "smoke script must check /nginx-health"
require_grep '/healthz' scripts/hf-space-smoke.sh "smoke script must check /healthz"
require_grep '/readyz' docker/healthcheck.sh "container healthcheck must wait for QwenPaw readiness"
require_grep '/_ops/health' scripts/hf-space-smoke.sh "smoke script must check /_ops/health"
require_grep 'ops-readyz' scripts/hf-space-smoke.sh "smoke script must check protected readiness"
require_grep 'qwenpaw-auth-boundary' scripts/hf-space-smoke.sh "smoke script must verify the QwenPaw auth boundary when configured"
require_grep '/_ops/persistence' scripts/hf-space-smoke.sh "smoke script must check /_ops/persistence when OPS_TOKEN is set"
require_grep '/_admin/api/status' scripts/admin-smoke.sh "admin smoke script must check /_admin/api/status"
require_grep 'ADMIN_EXPECTED_ENABLED' scripts/admin-smoke.sh "admin smoke script must keep disabled-by-default mode explicit"
require_grep 'web-root' scripts/hf-space-smoke.sh "smoke script must check the web root"
require_grep 'listen 7860 default_server;' docker/nginx.conf "Nginx must listen on 7860 as the default server"
require_grep 'limit_except GET' docker/nginx.conf "Nginx ops route must reject non-GET methods"
require_grep 'limit_except GET POST' docker/nginx.conf "Nginx admin route must reject unexpected methods"
require_grep 'client_max_body_size 16k;' docker/nginx.conf "Nginx ops route must keep a small body limit"
require_grep 'client_max_body_size 64k;' docker/nginx.conf "Nginx admin route must keep a small body limit"
require_grep 'fastcgi_temp_path[[:space:]]+/tmp/qwenpaw-run/nginx-fastcgi;' docker/nginx.conf "Nginx must use writable fastcgi temp path"
require_grep 'uwsgi_temp_path[[:space:]]+/tmp/qwenpaw-run/nginx-uwsgi;' docker/nginx.conf "Nginx must use writable uwsgi temp path"
require_grep 'scgi_temp_path[[:space:]]+/tmp/qwenpaw-run/nginx-scgi;' docker/nginx.conf "Nginx must use writable scgi temp path"
require_absent '\$proxy_add_x_forwarded_for' docker/nginx.conf "Nginx must not forward a client-supplied X-Forwarded-For chain"
require_grep 'X-Forwarded-For[[:space:]]+\$remote_addr;' docker/nginx.conf "Nginx must replace X-Forwarded-For with its direct peer address"
require_grep 'nginx -t -c /home/user/app/docker/nginx.conf' docker/entrypoint.sh "entrypoint must validate Nginx config before supervisor"
require_grep 'prepare_runtime_config\.py' docker/entrypoint.sh "entrypoint must migrate trusted proxy configuration"
require_grep 'trusted_proxies' docker/prepare_runtime_config.py "runtime config migration must manage trusted proxies"
require_grep '127\.0\.0\.1/32' docker/prepare_runtime_config.py "runtime config migration must trust only the local Nginx proxy by default"
require_grep '/api/healthz' docker/ops_service.py "ops readiness must use the upstream QwenPaw readiness endpoint"
require_grep 'path == "/readyz"' docker/ops_service.py "public readyz must require upstream readiness"
require_grep 'autorestart=unexpected' docker/supervisord.conf "QwenPaw supervisor policy must not restart clean exits"
require_grep 'startretries=5' docker/supervisord.conf "QwenPaw supervisor policy must bound startup retries"
require_grep 'startsecs=10' docker/supervisord.conf "QwenPaw supervisor policy must require a stable startup window"
require_grep 'Content-Security-Policy' docker/ops_service.py "ops service must emit a CSP header"
require_grep 'Content-Security-Policy' docker/admin_service.py "admin service must emit a CSP header"
require_grep 'hmac.compare_digest' docker/ops_service.py "ops service must compare tokens with hmac.compare_digest"
require_grep 'hmac.compare_digest' docker/admin_service.py "admin service must compare tokens with hmac.compare_digest"

if [ "$errors" -gt 0 ]; then
  exit 1
fi

printf 'PASS hfs-contract: Pattern A source-fetch contract is structurally valid\n'
