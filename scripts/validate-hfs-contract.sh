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
require_file .gitattributes
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
require_file scripts/export_hfs_space_bundle.py
require_file scripts/export_space_bundle.py
require_file scripts/test_release_tools.py
require_file .github/workflows/deploy-hf-space.yml
require_file .github/workflows/deploy-hfs-formal.yml
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
    },
    "optional_secrets": {
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

category_names = list(expected_lists)
for index, left in enumerate(category_names):
    for right in category_names[index + 1 :]:
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

python3 - "$repo_root" <<'PY_VALIDATE_RELEASE_PROFILES'
from __future__ import annotations

import re
import runpy
import sys
from pathlib import Path

root = Path(sys.argv[1])
failures: list[str] = []
expected_spaces = {
    "candidate": "BlueSkyXN/QwenPaw-all-in-one-HFS-v2-candidate",
    "formal": "BlueSkyXN/QwenPaw-all-in-one-HFS",
}
expected_manifests = {
    "candidate": "hfs-dev.candidate.toml",
    "formal": "hfs-dev.toml",
}
expected_paths = {
    ".dockerignore",
    ".gitattributes",
    "BUILD_SOURCE.json",
    "Dockerfile",
    "LICENSE",
    "README.md",
    "SHA256SUMS",
    "hfs-dev.toml",
    "docker/admin_service.py",
    "docker/entrypoint.sh",
    "docker/healthcheck.sh",
    "docker/nginx.conf",
    "docker/ops_service.py",
    "docker/prepare_runtime_config.py",
    "docker/qwenpaw.env.runtime",
    "docker/supervisord.conf",
}

if (root / ".gitattributes").read_text(encoding="utf-8") != "* text=auto eol=lf\n":
    failures.append(".gitattributes must contain only the HFS bundle LF text contract")

exporter_path = root / "scripts" / "export_hfs_space_bundle.py"
namespace = runpy.run_path(str(exporter_path))
if tuple(namespace.get("PROFILE_NAMES", ())) != ("candidate", "formal"):
    failures.append("HFS exporter must accept only the candidate/formal enum profiles")
profiles = namespace.get("PROFILES", {})
if set(profiles) != set(expected_spaces):
    failures.append("HFS exporter profile allowlist must contain exactly candidate and formal")
for profile_name, expected_space in expected_spaces.items():
    profile = profiles.get(profile_name, {})
    if profile.get("space") != expected_space:
        failures.append(f"{profile_name} exporter profile must fix Space id {expected_space}")
    if profile.get("manifest") != expected_manifests[profile_name]:
        failures.append(f"{profile_name} exporter profile must fix its reviewed manifest")
if set(namespace.get("BUNDLE_PATHS", ())) != expected_paths:
    failures.append("HFS exporter final path allowlist does not match the reviewed wrapper boundary")
source_to_bundle = namespace.get("source_to_bundle")
if not callable(source_to_bundle):
    failures.append("HFS exporter must expose fixed per-profile source mappings")
else:
    for profile_name, manifest_path in expected_manifests.items():
        mapping = source_to_bundle(profile_name)
        if mapping.get(manifest_path) != "hfs-dev.toml":
            failures.append(f"{profile_name} exporter must normalize its manifest to hfs-dev.toml")
        if set(mapping.values()) | {"BUILD_SOURCE.json", "SHA256SUMS"} != expected_paths:
            failures.append(f"{profile_name} exporter source mapping differs from the strict path allowlist")
if "hfs-dev.candidate.toml" in expected_paths:
    failures.append("candidate manifest filename must not leak into an exported Space root")

exporter_source = exporter_path.read_text(encoding="utf-8")
for forbidden_argument in ('add_argument("--space"', 'add_argument("--owner"', 'add_argument("--repo"'):
    if forbidden_argument in exporter_source:
        failures.append(f"HFS exporter must not accept an arbitrary target argument: {forbidden_argument}")

formal_samples = {
    'space = "BlueSkyXN/QwenPaw-all-in-one-HFS"',
    "https://huggingface.co/spaces/BlueSkyXN/QwenPaw-all-in-one-HFS",
    "https://blueskyxn-qwenpaw-all-in-one-hfs.hf.space",
    "HF_SPACE_ID=BlueSkyXN/QwenPaw-all-in-one-HFS",
}
patterns = namespace.get("FORMAL_TARGET_PATTERNS", ())
for sample in formal_samples:
    if not any(pattern.search(sample) for pattern in patterns):
        failures.append(f"candidate exporter lacks a production-target leak guard for {sample}")
candidate_samples = {
    f'space = "{expected_spaces["candidate"]}"',
    f"https://huggingface.co/spaces/{expected_spaces['candidate']}",
    "https://blueskyxn-qwenpaw-all-in-one-hfs-v2-candidate.hf.space",
    f"HF_SPACE_ID={expected_spaces['candidate']}",
    "https://github.com/BlueSkyXN/QwenPaw-all-in-one-HFS",
}
for sample in candidate_samples:
    if any(pattern.search(sample) for pattern in patterns):
        failures.append(f"production-target leak guard incorrectly rejects an allowed candidate/source value: {sample}")

candidate_workflow = (root / ".github" / "workflows" / "deploy-hf-space.yml").read_text(encoding="utf-8")
candidate_markers = {
    "workflow_dispatch:": "candidate deploy must be manually dispatched",
    "source_ref:": "candidate deploy must require source_ref",
    "confirm_upload:": "candidate deploy must require explicit upload confirmation",
    "PUBLISH_CANDIDATE": "candidate deploy must use the reviewed confirmation phrase",
    "contents: read": "candidate deploy must keep GitHub permissions read-only",
    "environment: hfs-candidate": "candidate deploy must use the hfs-candidate environment",
    f"CANDIDATE_SPACE: {expected_spaces['candidate']}": "candidate deploy must fix the target Space",
    "bash scripts/static-check.sh": "candidate deploy must run the repository static gate",
    "export_hfs_space_bundle.py export": "candidate deploy must export an allowlisted bundle",
    "--profile candidate": "candidate deploy must select only the candidate profile",
    "export_hfs_space_bundle.py verify": "candidate deploy must verify export and readback",
    "origin/main": "candidate deploy must bind source_ref to GitHub main",
    "GITHUB_SHA": "candidate deploy must bind source_ref to the dispatched GitHub SHA",
    "info.private is not True": "candidate deploy must fail unless the Space is private",
    "actual - expected": "candidate preflight must reject remote paths outside the allowlist",
    "actual != expected": "candidate readback must require the exact final path set",
    "hf upload": "candidate deploy must upload only after verification",
    "hf download": "candidate deploy must perform complete repository readback",
    "cmp \"$bundle/SHA256SUMS\"": "candidate deploy must compare the checksum manifest after readback",
}
for marker, message in candidate_markers.items():
    if marker not in candidate_workflow:
        failures.append(message)
if re.search(r"(?m)^\s{2}(?:push|pull_request|schedule):", candidate_workflow):
    failures.append("candidate deploy must not have an automatic trigger")
hf_token_bindings = re.findall(r"(?m)^\s*HF_TOKEN:\s*(.+?)\s*$", candidate_workflow)
if not hf_token_bindings or any(binding != "${{ secrets.HF_TOKEN }}" for binding in hf_token_bindings):
    failures.append("candidate deploy HF_TOKEN must come only from the GitHub environment Secret")
for forbidden in (
    "hf repo delete",
    "hf repos delete",
    "delete_repo(",
    "hf spaces restart",
    "restart_space(",
    "hf spaces variables set",
    "hf spaces secrets set",
    "hf spaces volumes set",
):
    if forbidden in candidate_workflow:
        failures.append(f"candidate deploy must not perform forbidden remote mutation: {forbidden}")

formal_workflow = (root / ".github" / "workflows" / "deploy-hfs-formal.yml").read_text(encoding="utf-8")
formal_markers = {
    "workflow_dispatch:": "formal deploy must be manually dispatched",
    "source_ref:": "formal deploy must require an exact source_ref",
    "confirm_upload:": "formal deploy must require explicit confirmation",
    "PUBLISH_FORMAL": "formal deploy must use the reviewed confirmation phrase",
    "contents: read": "formal deploy must keep GitHub permissions read-only",
    "environment: hfs-production": "formal deploy must use the hfs-production environment",
    f"FORMAL_SPACE: {expected_spaces['formal']}": "formal deploy must fix the canonical private Space",
    'HF_CLI_VERSION: "1.5.0"': "formal deploy must pin huggingface_hub 1.5.0",
    'huggingface_hub==${HF_CLI_VERSION}': "formal deploy must install the pinned Hugging Face client",
    "bash scripts/static-check.sh": "formal deploy must run the repository static gate",
    "export_hfs_space_bundle.py export": "formal deploy must export the strict bundle",
    "--profile formal": "formal deploy must select the fixed formal profile",
    "export_hfs_space_bundle.py verify": "formal deploy must verify export and readback",
    "origin/main": "formal deploy must bind source_ref to GitHub main",
    "GITHUB_SHA": "formal deploy must bind source_ref to the dispatched GitHub SHA",
    "info.private is not True": "formal deploy must fail unless the canonical Space is private",
    "actual - expected": "formal preflight must reject remote paths outside the allowlist",
    "actual != expected": "formal readback must require the exact path set",
    "huggingface_hub.cli.hf upload": "formal deploy must upload only the verified bundle",
    "huggingface_hub.cli.hf download": "formal deploy must perform a complete readback",
    'cmp "$bundle/BUILD_SOURCE.json"': "formal deploy must compare provenance after readback",
    'cmp "$bundle/SHA256SUMS"': "formal deploy must compare checksums after readback",
    'evidence.get("wrapper_source_commit")': "formal deploy must bind readback provenance to source_ref",
    "restart_space(": "formal deploy must request a Space restart after readback",
    "factory_reboot=True": "formal deploy restart must use the factory path",
}
for marker, message in formal_markers.items():
    if marker not in formal_workflow:
        failures.append(message)
if re.search(r"(?m)^\s{2}(?:push|pull_request|schedule):", formal_workflow):
    failures.append("formal deploy must not have an automatic trigger")
formal_hf_token_bindings = re.findall(r"(?m)^\s*HF_TOKEN:\s*(.+?)\s*$", formal_workflow)
if not formal_hf_token_bindings or any(
    binding != "${{ secrets.HF_TOKEN }}" for binding in formal_hf_token_bindings
):
    failures.append("formal deploy HF_TOKEN must come only from the hfs-production environment Secret")
for forbidden_input in ("owner:", "repo_id:", "target_space:"):
    if forbidden_input in formal_workflow:
        failures.append(f"formal deploy must not accept or declare arbitrary target input: {forbidden_input}")
for forbidden in (
    "hf repo delete",
    "hf repos delete",
    "delete_repo(",
    "create_repo(",
    "hf spaces variables set",
    "hf spaces secrets set",
    "hf spaces volumes set",
):
    if forbidden in formal_workflow:
        failures.append(f"formal deploy must not perform unrelated remote mutation: {forbidden}")

sync_source = (root / "scripts" / "hf_space_sync.py").read_text(encoding="utf-8")
test_source = (root / "scripts" / "test_release_tools.py").read_text(encoding="utf-8")
for marker in (
    "test_exports_candidate_bundle_with_exact_allowlist_and_checksums",
    "test_exports_formal_bundle_with_fixed_target_and_provenance",
    "test_verifier_rejects_profile_mismatch",
    "test_formal_verifier_rejects_provenance_target_tampering",
    "test_exporter_rejects_non_allowlisted_profile",
):
    if marker not in test_source:
        failures.append(f"release tools tests lack required profile contract case: {marker}")
for marker in (
    'string_list(manifest, "optional_secrets")',
    "configured_optional_secrets",
    "managed_secrets = secrets | optional_secrets",
    "remote_secrets - managed_secrets",
):
    if marker not in sync_source:
        failures.append(f"Settings sync lacks optional Secret contract marker: {marker}")
for marker in (
    "test_empty_optional_secret_is_accepted",
    "test_missing_required_secret_is_rejected",
    "test_nonempty_optional_placeholder_is_rejected",
    "test_configured_optional_secret_is_pushed_and_required_on_readback",
    "test_prune_retains_registered_optional_secret_when_local_value_is_empty",
):
    if marker not in test_source:
        failures.append(f"release tools tests lack required optional Secret case: {marker}")

if failures:
    for failure in failures:
        print(f"FAIL hfs-contract: {failure}", file=sys.stderr)
    raise SystemExit(1)
PY_VALIDATE_RELEASE_PROFILES

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
