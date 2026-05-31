---
title: QwenPaw All-in-One
emoji: 🐾
colorFrom: blue
colorTo: indigo
sdk: docker
app_port: 7860
suggested_hardware: cpu-upgrade
pinned: false
---

# QwenPaw All-in-One for Hugging Face Docker Space

This repository is a **Pattern A HFS Port Repository** for running QwenPaw on Hugging Face Docker Space.

It is not the upstream QwenPaw product source. It maintains the Hugging Face Space delivery package:

- root-level Space card and Dockerfile
- rootless Docker runtime
- Nginx single public port
- Supervisor process layout
- `/data` persistence boundary
- read-only `/_ops` diagnostics
- disabled-by-default `/_admin` management shell
- smoke/static checks and HFS alignment documentation

## HFS Classification

```text
Pattern: A — HFS Port Repository
Runtime mode: artifact-at-build-time
Space root: repo root
Source of truth: upstream QwenPaw PyPI package / upstream QwenPaw repository
Maintained here: HFS runtime glue, Nginx, Supervisor, ops/admin, docs, smoke and CI
```

Do **not** move the Space implementation to `cloud/hfs/`. This repository root is the Hugging Face Space root.

## Runtime Shape

Only one public port is exposed:

```text
Nginx :7860
  ├─ /                  -> QwenPaw app :8088
  ├─ /nginx-health      -> Nginx liveness
  ├─ /healthz           -> ops-service comprehensive health
  ├─ /readyz            -> ops-service readiness
  ├─ /_ops/*            -> ops-service :8081
  └─ /_admin/*          -> admin-service :8082, disabled by default

Internal processes:
  ├─ Xvfb :99
  ├─ QwenPaw app via dbus-run-session
  ├─ Nginx
  ├─ ops-service
  └─ admin-service
```

## Persistence Layout

Enable Hugging Face **Persistent Storage** before treating runtime data as durable.

```text
/data/qwenpaw/working      QwenPaw config, memory, skills and runtime state
/data/qwenpaw/secrets      provider configuration, API keys and local secrets
/data/qwenpaw/backups      QwenPaw backup archives
/data/var/logs             Nginx, QwenPaw, Xvfb, ops and admin logs
/tmp/qwenpaw-run           pid files, Supervisor socket and Nginx temp files
```

The container initializes QwenPaw with `qwenpaw init --defaults --accept-security` if `/data/qwenpaw/working/config.json` does not exist.

## Recommended Hugging Face Settings

Use a **Private** or **Protected** Space. QwenPaw is a personal assistant and may hold sensitive memory, files, provider keys and channel tokens.

Recommended Variables:

```env
PORT=7860
QWENPAW_PORT=8088
QWENPAW_WORKING_DIR=/data/qwenpaw/working
QWENPAW_SECRET_DIR=/data/qwenpaw/secrets
QWENPAW_BACKUP_DIR=/data/qwenpaw/backups
QWENPAW_DISABLED_CHANNELS=imessage
QWENPAW_AUTH_ENABLED=true
QWENPAW_TELEMETRY_OPT_OUT=1
ADMIN_ENABLED=false
```

Recommended Secrets:

```env
OPS_TOKEN=<strong-random-token>
ADMIN_TOKEN=<strong-random-token-if-admin-enabled>
ADMIN_CSRF_TOKEN=<strong-random-csrf-token-if-admin-enabled>
DASHSCOPE_API_KEY=<optional>
OPENAI_API_KEY=<optional>
GEMINI_API_KEY=<optional>
TELEGRAM_BOT_TOKEN=<optional>
DISCORD_BOT_TOKEN=<optional>
```

`/_ops/config` reports only secret presence booleans, never secret values.

## Build

Development build:

```bash
docker build \
  -t qwenpaw-all-in-one-hfs:dev \
  --build-arg QWENPAW_VERSION=1.1.9 \
  --build-arg QWENPAW_PACKAGE_SHA256=73ff2ca8b22dbfd6d233b678fb1de040bb41a1bff8b2b4091ecde866e1e57f63 \
  .
```

Release-style build:

```bash
docker build \
  -t qwenpaw-all-in-one-hfs:release \
  --build-arg BASE_IMAGE_REF='node:22-slim@sha256:<digest>' \
  --build-arg QWENPAW_VERSION='1.1.9' \
  --build-arg QWENPAW_PACKAGE_SHA256='73ff2ca8b22dbfd6d233b678fb1de040bb41a1bff8b2b4091ecde866e1e57f63' \
  --build-arg UV_VERSION='0.7.20' \
  --build-arg QWENPAW_UPSTREAM_REF='2d9527bb097f9b09428190f80e1f3fd44f2ff453' \
  .
```

`QWENPAW_PACKAGE_SHA256` is the verified PyPI wheel hash for `qwenpaw==1.1.9`. If you change `QWENPAW_VERSION`, update the hash at the same time.

## Local Run

```bash
docker run --rm -it \
  -p 7860:7860 \
  -v qwenpaw-hfs-data:/data \
  -e OPS_TOKEN=dev-ops-token \
  -e QWENPAW_AUTH_ENABLED=true \
  qwenpaw-all-in-one-hfs:dev
```

Open:

```text
http://127.0.0.1:7860/
```

Smoke:

```bash
OPS_TOKEN=dev-ops-token \
  bash scripts/hf-space-smoke.sh http://127.0.0.1:7860
```

## Diagnostics

Public liveness:

```text
/nginx-health
/healthz
/readyz
```

Protected read-only diagnostics:

```text
/_ops/health
/_ops/healthz
/_ops/readyz
/_ops/status
/_ops/system
/_ops/config
/_ops/version
/_ops/logs?service=qwenpaw
/_ops/errors
/_ops/metrics
```

Use one of:

```text
X-Ops-Token: <OPS_TOKEN>
Authorization: Bearer <OPS_TOKEN>
```

Browser diagnostics may use `/_ops/?token=<OPS_TOKEN>` and will only show a basic read-only dashboard.

## Admin Surface

`/_admin` is disabled by default and returns `404` unless explicitly enabled:

```env
ADMIN_ENABLED=true
ADMIN_TOKEN=<strong-random-token>
ADMIN_CSRF_TOKEN=<strong-random-csrf-token>
```

Mutating API calls require token authentication, `X-CSRF-Token: <ADMIN_CSRF_TOKEN>` and `confirm=true`. Supported actions are intentionally narrow:

```text
POST /_admin/api/actions/restart-service
POST /_admin/api/actions/reload-nginx
POST /_admin/api/actions/run-health-checks
GET  /_admin/api/audit?limit=50
```

## Validation

```bash
bash scripts/static-check.sh
bash scripts/validate-hfs-contract.sh
```

The static gate checks repository shape and Python/shell syntax only. It does not replace Docker build, Hugging Face runtime takeover or live endpoint smoke.

## Production Boundary

This is an HFS demo / personal deployment package. It is not a high-availability production architecture. For sensitive use, keep the Space private/protected, enable authentication, configure strong tokens and review `docs/security.md`.
