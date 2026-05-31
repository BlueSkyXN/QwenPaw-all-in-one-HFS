#!/usr/bin/env bash
set -euo pipefail

export PORT="${PORT:-7860}"
export QWENPAW_PORT="${QWENPAW_PORT:-8088}"
export QWENPAW_WORKING_DIR="${QWENPAW_WORKING_DIR:-/data/qwenpaw/working}"
export QWENPAW_SECRET_DIR="${QWENPAW_SECRET_DIR:-/data/qwenpaw/secrets}"
export QWENPAW_BACKUP_DIR="${QWENPAW_BACKUP_DIR:-/data/qwenpaw/backups}"
export QWENPAW_RUNNING_IN_CONTAINER="${QWENPAW_RUNNING_IN_CONTAINER:-1}"
export QWENPAW_TELEMETRY_OPT_OUT="${QWENPAW_TELEMETRY_OPT_OUT:-1}"
export PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH="${PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH:-/usr/bin/chromium}"
export PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD="${PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD:-1}"
export QWENPAW_DISABLED_CHANNELS="${QWENPAW_DISABLED_CHANNELS:-imessage}"

mkdir -p \
  "$QWENPAW_WORKING_DIR" \
  "$QWENPAW_SECRET_DIR" \
  "$QWENPAW_BACKUP_DIR" \
  /data/var/logs \
  /tmp/qwenpaw-run/nginx-client-body \
  /tmp/qwenpaw-run/nginx-proxy \
  /tmp/qwenpaw-run/nginx-fastcgi \
  /tmp/qwenpaw-run/nginx-uwsgi \
  /tmp/qwenpaw-run/nginx-scgi \
  /tmp/qwenpaw-run/supervisor \
  /tmp/qwenpaw-cache

if [ -w /data ]; then
  date -u +%Y-%m-%dT%H:%M:%SZ > /data/.qwenpaw_hfs_persistent_storage_probe || true
else
  echo "WARNING: /data is not writable. Runtime state may be lost." >&2
fi

case "$(printf '%s' "$QWENPAW_TELEMETRY_OPT_OUT" | tr '[:upper:]' '[:lower:]')" in
  1|true|yes|on)
    if [ ! -f "${QWENPAW_WORKING_DIR}/.telemetry_collected" ]; then
      printf '{"opted_out": true, "collected_versions": []}\n' > "${QWENPAW_WORKING_DIR}/.telemetry_collected"
    fi
    ;;
esac

if [ ! -f "${QWENPAW_WORKING_DIR}/config.json" ]; then
  echo "No QwenPaw config found in ${QWENPAW_WORKING_DIR}; running qwenpaw init"
  qwenpaw init --defaults --accept-security
else
  echo "QwenPaw config found in ${QWENPAW_WORKING_DIR}; skipping init"
fi

if [ -z "${QWENPAW_AUTH_ENABLED:-${COPAW_AUTH_ENABLED:-}}" ]; then
  cat >&2 <<'EOF'
============================================================
SECURITY NOTICE: QWENPAW_AUTH_ENABLED is not set.
For Hugging Face Spaces, use a Private/Protected Space and enable QwenPaw authentication.
============================================================
EOF
fi

nginx -t -c /home/user/app/docker/nginx.conf

exec /usr/bin/supervisord -c /home/user/app/docker/supervisord.conf
