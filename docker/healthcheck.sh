#!/usr/bin/env bash
set -euo pipefail
port="${PORT:-7860}"
curl -fsS --max-time 5 "http://127.0.0.1:${port}/readyz" >/dev/null
