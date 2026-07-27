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
require_file hfs-dev.candidate.toml
require_file .env.example
require_file .gitignore
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
require_file scripts/hf_space_sync.py
require_file docs/hfs-alignment.md

python3 - "$repo_root" <<'PY_VALIDATE_HFS'
from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path

root = Path(sys.argv[1])
manifest_path = root / "hfs-dev.toml"
raw = manifest_path.read_text(encoding="utf-8")
manifest = tomllib.loads(raw)

expected_scalars = {
    "standard": "2.0",
    "project": "qwenpaw-all-in-one-hfs",
    "space": "BlueSkyXN/QwenPaw-all-in-one-HFS",
    "sovereignty": "port",
    "lane": "source",
    "version_source": "commit",
}
expected_lists = {
    "local_only": {
        "GH_TOKEN",
        "HF_TOKEN",
        "GH_REPO",
        "HF_SPACE_ID",
        "HF_SPACE_URL",
        "HF_PUBLIC_URL",
        "HF_STORAGE_BUCKET",
        "SMOKE_BASE_URL",
        "QWENPAW_ADMIN_USERNAME",
        "QWENPAW_ADMIN_PASSWORD",
        "ADMIN_EXPECTED_ENABLED",
        "ADMIN_SMOKE_ACTIONS",
    },
    "secrets": {
        "OPS_TOKEN",
        "ADMIN_TOKEN",
        "ADMIN_CSRF_TOKEN",
        "DASHSCOPE_API_KEY",
        "OPENAI_API_KEY",
        "GEMINI_API_KEY",
        "TELEGRAM_BOT_TOKEN",
        "DISCORD_BOT_TOKEN",
    },
    "variables": {
        "PORT",
        "QWENPAW_PORT",
        "QWENPAW_WORKING_DIR",
        "QWENPAW_SECRET_DIR",
        "QWENPAW_BACKUP_DIR",
        "QWENPAW_DISABLED_CHANNELS",
        "QWENPAW_AUTH_ENABLED",
        "QWENPAW_TELEMETRY_OPT_OUT",
        "ADMIN_ENABLED",
        "QWENPAW_OPS_PORT",
        "QWENPAW_ADMIN_PORT",
        "QWENPAW_OPS_LOG_DIR",
        "QWENPAW_ADMIN_AUDIT_LOG",
        "OPS_SESSION_TTL_SECONDS",
        "OPS_COOKIE_SECURE",
    },
}
allowed_keys = set(expected_scalars) | set(expected_lists)
env_key = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
token_literal = re.compile(
    r"(?:hf_[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9]{20,})"
)
failures: list[str] = []

for key, value in expected_scalars.items():
    if manifest.get(key) != value:
        failures.append(f"hfs-dev.toml {key} must be {value!r}, got {manifest.get(key)!r}")

unexpected_keys = sorted(set(manifest) - allowed_keys)
if unexpected_keys:
    failures.append("hfs-dev.toml must remain the minimal v2 semantic manifest; unexpected keys: " + ", ".join(unexpected_keys))

seen_categories: dict[str, set[str]] = {}
for field, expected in expected_lists.items():
    value = manifest.get(field)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        failures.append(f"hfs-dev.toml {field} must be a string array")
        continue
    invalid = sorted(item for item in value if not item or not env_key.fullmatch(item))
    if invalid:
        failures.append(f"hfs-dev.toml {field} has invalid environment keys: {invalid}")
    duplicates = sorted({item for item in value if value.count(item) > 1})
    if duplicates:
        failures.append(f"hfs-dev.toml {field} has duplicate environment keys: {duplicates}")
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        details = []
        if missing:
            details.append("missing " + ", ".join(missing))
        if extra:
            details.append("unexpected " + ", ".join(extra))
        failures.append(f"hfs-dev.toml {field} classification mismatch: {'; '.join(details)}")
    seen_categories[field] = actual

for left, right in (("local_only", "secrets"), ("local_only", "variables"), ("secrets", "variables")):
    overlap = sorted(seen_categories.get(left, set()) & seen_categories.get(right, set()))
    if overlap:
        failures.append(f"hfs-dev.toml {left} and {right} must be mutually exclusive: {overlap}")

if token_literal.search(raw):
    failures.append("hfs-dev.toml must register environment key names only, not token literals")

template_keys: list[str] = []
for line in (root / ".env.example").read_text(encoding="utf-8").splitlines():
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        continue
    if "=" not in stripped:
        failures.append(f".env.example has a malformed entry: {line!r}")
        continue
    key, _ = stripped.split("=", 1)
    if not env_key.fullmatch(key):
        failures.append(f".env.example has an invalid environment key: {key!r}")
    template_keys.append(key)

template_duplicates = sorted({item for item in template_keys if template_keys.count(item) > 1})
if template_duplicates:
    failures.append(f".env.example has duplicate environment keys: {template_duplicates}")
registered_keys = set().union(*expected_lists.values())
if set(template_keys) != registered_keys:
    missing = sorted(registered_keys - set(template_keys))
    extra = sorted(set(template_keys) - registered_keys)
    details = []
    if missing:
        details.append("missing " + ", ".join(missing))
    if extra:
        details.append("unregistered " + ", ".join(extra))
    failures.append(".env.example must contain exactly the registered HFS keys: " + "; ".join(details))
if token_literal.search((root / ".env.example").read_text(encoding="utf-8")):
    failures.append(".env.example must not contain token literals")

if failures:
    for failure in failures:
        print(f"FAIL hfs-contract: {failure}", file=sys.stderr)
    raise SystemExit(1)
PY_VALIDATE_HFS

python3 - "$repo_root" <<'PY_VALIDATE_PROFILE'
import sys
import tomllib
from pathlib import Path

root = Path(sys.argv[1])
production = tomllib.loads((root / "hfs-dev.toml").read_text(encoding="utf-8"))
candidate = tomllib.loads((root / "hfs-dev.candidate.toml").read_text(encoding="utf-8"))
if candidate.get("space") != "BlueSkyXN/QwenPaw-all-in-one-HFS-v2-candidate":
    raise SystemExit("candidate manifest has the wrong fixed Space id")
for key in sorted(set(production) | set(candidate)):
    if key != "space" and production.get(key) != candidate.get(key):
        raise SystemExit(f"candidate manifest differs from production at {key}")
PY_VALIDATE_PROFILE

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
require_grep 'Space root: repo root' docs/hfs-alignment.md "docs/hfs-alignment.md must declare repo root as Space root"
require_grep 'lane = "source"' docs/hfs-alignment.md "docs/hfs-alignment.md must declare the source lane"

python3 - <<'PY_DOCKER_PINS'
from __future__ import annotations

import re
from pathlib import Path

args: dict[str, str] = {}
for line in Path("Dockerfile").read_text(encoding="utf-8").splitlines():
    match = re.fullmatch(r"ARG ([A-Z_][A-Z0-9_]*)=(.*)", line)
    if match:
        args[match.group(1)] = match.group(2)

required = {
    "BASE_IMAGE_REF",
    "QWENPAW_SOURCE_REPO",
    "QWENPAW_SOURCE_REF",
    "QWENPAW_SOURCE_VERSION",
    "QWENPAW_CONSOLE_BUNDLE_URL",
    "QWENPAW_CONSOLE_BUNDLE_SHA256",
    "UV_VERSION",
}
missing = sorted(required - set(args))
failures: list[str] = []
if missing:
    failures.append("Dockerfile missing build args: " + ", ".join(missing))
else:
    if not re.fullmatch(r"node:22-slim@sha256:[0-9a-f]{64}", args["BASE_IMAGE_REF"]):
        failures.append("BASE_IMAGE_REF must use the node:22-slim immutable digest")
    if args["QWENPAW_SOURCE_REPO"] != "https://github.com/agentscope-ai/QwenPaw.git":
        failures.append("QWENPAW_SOURCE_REPO must identify the upstream QwenPaw repository")
    source_ref = args["QWENPAW_SOURCE_REF"]
    if not re.fullmatch(r"[0-9a-f]{40}", source_ref):
        failures.append("QWENPAW_SOURCE_REF must be a complete immutable commit SHA")
    if not re.fullmatch(r"[0-9]+(?:\.[0-9]+)+", args["QWENPAW_SOURCE_VERSION"]):
        failures.append("QWENPAW_SOURCE_VERSION must be a concrete source version")
    if source_ref not in args["QWENPAW_CONSOLE_BUNDLE_URL"]:
        failures.append("QWENPAW_CONSOLE_BUNDLE_URL must identify the complete pinned source SHA")
    if not re.fullmatch(r"[0-9a-f]{64}", args["QWENPAW_CONSOLE_BUNDLE_SHA256"]):
        failures.append("QWENPAW_CONSOLE_BUNDLE_SHA256 must be a SHA-256 digest")
    if not re.fullmatch(r"[0-9]+(?:\.[0-9]+)+", args["UV_VERSION"]):
        failures.append("UV_VERSION must be a concrete version")

if failures:
    for failure in failures:
        print(f"FAIL hfs-contract: {failure}")
    raise SystemExit(1)
PY_DOCKER_PINS

require_grep '^FROM \${BASE_IMAGE_REF} AS runtime$' Dockerfile "Dockerfile must select base runtime image from BASE_IMAGE_REF"
require_grep 'git fetch --depth 1 origin "\${QWENPAW_SOURCE_REF}"' Dockerfile "Dockerfile must fetch the pinned upstream source ref"
require_grep 'src/qwenpaw/__version__\.py' Dockerfile "Dockerfile must validate the upstream source version"
require_grep 'sha256sum -c -' Dockerfile "Dockerfile must verify the console bundle before extraction"
require_grep 'tar -xzf /tmp/qwenpaw-console\.tar\.gz -C src/qwenpaw/console' Dockerfile "Dockerfile must extract verified console assets into the Python package source"
require_grep 'test -f src/qwenpaw/console/index\.html' Dockerfile "Dockerfile must require the console entrypoint"
require_absent 'npm ci --include=dev' Dockerfile "HFS worker must not rebuild the memory-heavy upstream console"
require_grep '/tmp/qwenpaw-src' Dockerfile "Dockerfile must install QwenPaw from fetched source"
require_absent 'qwenpaw==\${QWENPAW_VERSION}' Dockerfile "Dockerfile must not install QwenPaw from PyPI package version in source-fetch mode"
require_absent '^ARG QWENPAW_PACKAGE_SHA256=' Dockerfile "Dockerfile must not expose PyPI artifact checksum in source-fetch mode"
require_grep 'fetch_source_ref' scripts/check-qwenpaw-pins.py "pin checker must fetch and validate the upstream source ref"
require_grep 'QWENPAW_SOURCE_VERSION matches upstream source' scripts/check-qwenpaw-pins.py "pin checker must validate upstream source version"
require_grep 'QWENPAW_CONSOLE_BUNDLE_SHA256 matches downloaded artifact' scripts/check-qwenpaw-pins.py "pin checker must validate the console bundle checksum"
require_grep 'EXPECTED_QWENPAW_SOURCE_REF' scripts/hf-space-smoke.sh "live smoke must verify the runtime source SHA"
require_grep 'console bundle provenance does not contain the runtime source SHA' scripts/hf-space-smoke.sh "live smoke must bind console provenance to source SHA"
require_grep 'payload\.get\("version", \{\}\)\.get\("release_pins", \{\}\)' scripts/hf-space-smoke.sh "live smoke must read provenance from the wrapped ops version payload"
require_grep 'hf_space_sync.py diff' docs/configuration.md "configuration docs must include Settings diff/readback"
require_grep 'hf_space_sync.py push' docs/configuration.md "configuration docs must include Settings push"
require_grep 'require-upstream-main' scripts/check-qwenpaw-pins.py "pin checker must support enforcing current upstream main"

require_absent '^ARG DIFY_' Dockerfile "QwenPaw HFS must not expose Dify image selectors"
require_absent '^FROM \${DIFY_' Dockerfile "QwenPaw HFS must not select Dify images"

require_grep '^local/$|^\*\*/local/$' .dockerignore ".dockerignore must exclude local/ from Docker build context"
require_grep '^\.env$' .dockerignore ".dockerignore must exclude the HFS .env value ledger"
require_grep '^\.env\.local$' .dockerignore ".dockerignore must exclude .env.local"
require_grep '^\*\.secret$' .dockerignore ".dockerignore must exclude *.secret"
require_grep '^\*\.key$' .dockerignore ".dockerignore must exclude *.key"
require_grep '^\*\.pem$' .dockerignore ".dockerignore must exclude *.pem"
require_grep '^\.env$' .gitignore ".gitignore must exclude the HFS .env value ledger"
require_grep '^\.env\.local$' .gitignore ".gitignore must explicitly exclude .env.local"
require_grep '^config\.toml$' .gitignore ".gitignore must exclude config.toml"
require_grep '^local/$' .gitignore ".gitignore must exclude local/"

require_grep 'QWENPAW_WORKING_DIR=/data/qwenpaw/working' Dockerfile "Dockerfile must persist QwenPaw working state under /data/qwenpaw"
require_grep 'QWENPAW_SECRET_DIR=/data/qwenpaw/secrets' Dockerfile "Dockerfile must persist QwenPaw secrets under /data/qwenpaw"
require_grep 'QWENPAW_BACKUP_DIR=/data/qwenpaw/backups' Dockerfile "Dockerfile must persist QwenPaw backups under /data/qwenpaw"
require_grep '/data/var/logs' Dockerfile "Dockerfile must keep runtime logs under /data/var/logs"
require_grep '/tmp/qwenpaw-run' Dockerfile "Dockerfile must keep transient runtime files under /tmp/qwenpaw-run"

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

printf 'PASS hfs-contract: Pattern A source-lane contract is structurally valid\n'
