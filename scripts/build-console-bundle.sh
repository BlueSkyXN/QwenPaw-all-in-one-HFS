#!/usr/bin/env bash
set -euo pipefail

source_repo="${1:?usage: $0 SOURCE_REPO SOURCE_REF SOURCE_VERSION OUTPUT_DIR}"
source_ref="${2:?usage: $0 SOURCE_REPO SOURCE_REF SOURCE_VERSION OUTPUT_DIR}"
source_version="${3:?usage: $0 SOURCE_REPO SOURCE_REF SOURCE_VERSION OUTPUT_DIR}"
output_dir="${4:?usage: $0 SOURCE_REPO SOURCE_REF SOURCE_VERSION OUTPUT_DIR}"

if [[ ! "$source_ref" =~ ^[0-9a-f]{40}$ ]]; then
  printf 'SOURCE_REF must be a 40-character lowercase commit SHA\n' >&2
  exit 2
fi

mkdir -p "$output_dir"
output_dir="$(cd "$output_dir" && pwd)"
work_dir="$(mktemp -d)"
cleanup() {
  rm -rf "$work_dir"
}
trap cleanup EXIT

source_dir="$work_dir/qwenpaw"
git init "$source_dir"
git -C "$source_dir" remote add origin "$source_repo"
git -C "$source_dir" fetch --depth 1 origin "$source_ref"
git -C "$source_dir" checkout --detach "$source_ref"
test "$(git -C "$source_dir" rev-parse HEAD)" = "$source_ref"

actual_version="$(python3 -c "import runpy; print(runpy.run_path('$source_dir/src/qwenpaw/__version__.py')['__version__'])")"
if [ "$actual_version" != "$source_version" ]; then
  printf 'source version mismatch: expected=%s actual=%s\n' "$source_version" "$actual_version" >&2
  exit 1
fi

(
  cd "$source_dir/console"
  NODE_ENV=development npm ci --include=dev --no-audit --no-fund
  NODE_OPTIONS="${NODE_OPTIONS:---max-old-space-size=8192}" npm run build
)

archive_name="qwenpaw-console-${source_ref}.tar.gz"
archive_path="$output_dir/$archive_name"
tar -C "$source_dir/console/dist" -czf "$archive_path" .
python3 - "$archive_path" <<'PY_CHECKSUM' >"$archive_path.sha256"
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

path = Path(sys.argv[1])
digest = hashlib.sha256(path.read_bytes()).hexdigest()
print(f"{digest}  {path.name}")
PY_CHECKSUM

printf 'console bundle: %s\n' "$archive_path"
printf 'console checksum: %s\n' "$archive_path.sha256"
