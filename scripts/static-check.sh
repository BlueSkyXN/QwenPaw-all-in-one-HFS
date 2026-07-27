#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$repo_root"

bash scripts/validate-hfs-contract.sh

# Optional external SKY-Prompt checker, when mounted or cloned by CI.
if [ -f hfs-dev/scripts/check_hfs_alignment.py ]; then
  python3 hfs-dev/scripts/check_hfs_alignment.py "$repo_root"
elif [ -f ../SKY-Prompt/hfs-dev/scripts/check_hfs_alignment.py ]; then
  python3 ../SKY-Prompt/hfs-dev/scripts/check_hfs_alignment.py "$repo_root"
else
  echo "INFO static-check: external hfs-dev checker not found; repository-local contract passed"
fi

bash -n docker/entrypoint.sh
bash -n docker/healthcheck.sh
bash -n scripts/admin-smoke.sh
bash -n scripts/hf-space-smoke.sh
bash -n scripts/local-build.sh
bash -n scripts/local-run.sh

PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s scripts -p 'test_runtime_helpers.py'

# compile() validates Python syntax without creating persistent .pyc files.
python3 - \
  docker/prepare_runtime_config.py \
  docker/ops_service.py \
  docker/admin_service.py \
  scripts/check-qwenpaw-pins.py \
  scripts/test_runtime_helpers.py <<'PY_COMPILE'
from __future__ import annotations

import sys
from pathlib import Path

for name in sys.argv[1:]:
    path = Path(name)
    compile(path.read_text(encoding="utf-8"), str(path), "exec")
PY_COMPILE

printf 'PASS static-check\n'
