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
    "runtime_mode": "artifact-at-build-time",
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
    "QWENPAW_VERSION": {"type": "package_version", "required_for_release": True, "dev_mutable_default_allowed": False},
    "QWENPAW_PACKAGE_SHA256": {"type": "checksum", "required_for_release": True, "dev_mutable_default_allowed": False, "release_requires_checksum": True},
    "UV_VERSION": {"type": "package_version", "required_for_release": True, "dev_mutable_default_allowed": True},
    "QWENPAW_UPSTREAM_REF": {"type": "metadata", "required_for_release": False, "dev_mutable_default_allowed": True, "metadata_only": True},
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
require_grep 'Runtime mode: artifact-at-build-time' docs/hfs-alignment.md "docs/hfs-alignment.md must declare artifact-at-build-time runtime mode"
require_grep 'Space root: repo root' docs/hfs-alignment.md "docs/hfs-alignment.md must declare repo root as Space root"

require_grep '^ARG BASE_IMAGE_REF=' Dockerfile "Dockerfile must expose BASE_IMAGE_REF build input"
require_grep '^ARG QWENPAW_VERSION=' Dockerfile "Dockerfile must expose QWENPAW_VERSION build input"
require_grep '^ARG QWENPAW_PACKAGE_SHA256=' Dockerfile "Dockerfile must expose QWENPAW_PACKAGE_SHA256 build input"
require_grep '^ARG UV_VERSION=' Dockerfile "Dockerfile must expose UV_VERSION build input"
require_grep '^ARG QWENPAW_UPSTREAM_REF=' Dockerfile "Dockerfile must expose QWENPAW_UPSTREAM_REF build input"
require_grep '^FROM \${BASE_IMAGE_REF} AS runtime$' Dockerfile "Dockerfile must select base runtime image from BASE_IMAGE_REF"
require_grep 'qwenpaw==\${QWENPAW_VERSION}' Dockerfile "Dockerfile must install QwenPaw from QWENPAW_VERSION"
require_grep 'QWENPAW_VERSION=1\.1\.12\.post2' Dockerfile "Dockerfile must default to the verified qwenpaw 1.1.12.post2 release"
require_grep 'QWENPAW_PACKAGE_SHA256=c07ba7780d0752281138298a6e2a7b0efd372bffab60e68d1d7e9856a5b16e6a' Dockerfile "Dockerfile must default to the verified qwenpaw 1.1.12.post2 wheel SHA256"
require_grep 'QWENPAW_UPSTREAM_REF=09fc515c88a5e817870e6b975e66b5be81893e03' Dockerfile "Dockerfile must record the verified upstream v1.1.12.post2 commit"
require_grep 'pypi.org/pypi/qwenpaw/json' scripts/check-qwenpaw-pins.py "pin checker must compare against PyPI package metadata"
require_grep 'git_remote_tag_commit' scripts/check-qwenpaw-pins.py "pin checker must compare QWENPAW_UPSTREAM_REF against upstream tag metadata"

require_absent '^ARG DIFY_' Dockerfile "QwenPaw HFS must not expose Dify image selectors"
require_absent '^FROM \${DIFY_' Dockerfile "QwenPaw HFS must not select Dify images"

require_grep '^local/$|^\*\*/local/$' .dockerignore ".dockerignore must exclude local/ from Docker build context"
require_grep '^\.env\.local$' .dockerignore ".dockerignore must exclude .env.local"
require_grep '^\*\.secret$' .dockerignore ".dockerignore must exclude *.secret"
require_grep '^\*\.key$' .dockerignore ".dockerignore must exclude *.key"
require_grep '^\*\.pem$' .dockerignore ".dockerignore must exclude *.pem"

require_grep '/nginx-health' scripts/hf-space-smoke.sh "smoke script must check /nginx-health"
require_grep '/healthz' scripts/hf-space-smoke.sh "smoke script must check /healthz"
require_grep '/_ops/health' scripts/hf-space-smoke.sh "smoke script must check /_ops/health"
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
require_grep 'nginx -t -c /home/user/app/docker/nginx.conf' docker/entrypoint.sh "entrypoint must validate Nginx config before supervisor"
require_grep 'Content-Security-Policy' docker/ops_service.py "ops service must emit a CSP header"
require_grep 'Content-Security-Policy' docker/admin_service.py "admin service must emit a CSP header"
require_grep 'hmac.compare_digest' docker/ops_service.py "ops service must compare tokens with hmac.compare_digest"
require_grep 'hmac.compare_digest' docker/admin_service.py "admin service must compare tokens with hmac.compare_digest"

if [ "$errors" -gt 0 ]; then
  exit 1
fi

printf 'PASS hfs-contract: Pattern A artifact-at-build-time contract is structurally valid\n'
