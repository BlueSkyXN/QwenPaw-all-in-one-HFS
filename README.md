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
- `/data` runtime-state boundary backed by an attached Hugging Face Storage Bucket
- read-only `/_ops` diagnostics
- disabled-by-default `/_admin` management surface
- smoke/static checks and HFS alignment documentation

## Project Links

```text
GitHub: https://github.com/BlueSkyXN/QwenPaw-all-in-one-HFS
Hugging Face Space: https://huggingface.co/spaces/BlueSkyXN/QwenPaw-all-in-one-HFS
Live app: https://blueskyxn-qwenpaw-all-in-one-hfs.hf.space
```

The Space should be treated as private/protected unless you have reviewed QwenPaw auth, provider keys, files, memory and channel integrations for your own deployment.

## Documentation

Start with [`docs/README.md`](docs/README.md). The main operator documents are:

- [`docs/deployment.md`](docs/deployment.md) for GitHub/Hugging Face deployment and runtime takeover.
- [`docs/configuration.md`](docs/configuration.md) for build args, runtime variables, secrets and local `.env.local` ledger keys.
- [`docs/ops-runbook.md`](docs/ops-runbook.md) for health checks, logs and failure triage.
- [`docs/release-checklist.md`](docs/release-checklist.md) for release pins, CI/HF verification and closeout.
- [`docs/security.md`](docs/security.md) for auth, secret handling and admin boundaries.

## HFS Classification

```text
Pattern: A - HFS Port Repository
Runtime mode: source-fetch
Space root: repo root
Source of truth: pinned upstream QwenPaw source commit plus checksum-matched console artifact
Maintained here: HFS runtime glue, Nginx, Supervisor, ops/admin, docs, smoke and CI
```

Do **not** move the Space implementation to `cloud/hfs/`. This repository root is the Hugging Face Space root.

## Runtime Shape

Only one public port is exposed:

```text
Nginx :7860
  ├─ /                  -> QwenPaw app :8088
  ├─ /nginx-health      -> Nginx liveness
  ├─ /healthz           -> QwenPaw process liveness
  ├─ /readyz            -> upstream /api/healthz readiness
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

Attach a private Hugging Face **Storage Bucket** read-write at `/data` before treating
runtime data as durable. Without that volume, `/data` belongs to the ephemeral Space
container and is lost on restart, rebuild or stop.

```bash
hf buckets create <namespace>/<bucket-name> --private --exist-ok
hf spaces volumes set <namespace>/<space-name> \
  -v hf://buckets/<namespace>/<bucket-name>:/data
hf spaces volumes list <namespace>/<space-name> --json
```

`hf spaces volumes set` replaces the complete volume list. When a Space already has
other mounts, repeat every required `-v` argument in the same command.

```text
/data/qwenpaw/working      QwenPaw config, memory, skills and runtime state
/data/qwenpaw/secrets      provider configuration, API keys and local secrets
/data/qwenpaw/backups      QwenPaw backup archives
/data/var/logs             Nginx, QwenPaw, Xvfb, ops and admin logs
/tmp/qwenpaw-run           pid files, Supervisor socket and Nginx temp files
```

The container initializes QwenPaw with `qwenpaw init --defaults --accept-security` if `/data/qwenpaw/working/config.json` does not exist.
On every start, the HFS entrypoint ensures `security.trusted_proxies` includes the local Nginx peer (`127.0.0.1/32`) without adding a broader network. Nginx replaces inbound forwarding headers with its direct peer address so an external request is not mistaken for loopback traffic by QwenPaw authentication.

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

## Maintainer Quick Start

Create a local ledger and fill only local/private values there:

```bash
cp .env.example .env.local
```

At minimum, set:

```env
GH_REPO=BlueSkyXN/QwenPaw-all-in-one-HFS
HF_SPACE_ID=BlueSkyXN/QwenPaw-all-in-one-HFS
HF_STORAGE_BUCKET=<namespace>/<bucket-name>
SMOKE_BASE_URL=https://blueskyxn-qwenpaw-all-in-one-hfs.hf.space
OPS_TOKEN=<same value configured in Hugging Face Space Settings>
```

For first-run browser verification, keep the admin login test record local-only:

```env
QWENPAW_ADMIN_USERNAME=<local-test-admin-name>
QWENPAW_ADMIN_PASSWORD=<local-test-admin-password>
```

Do not commit `.env.local`, screenshots, runtime data, logs, databases, keys or exported secrets. They are ignored by `.gitignore` and `.dockerignore`.

## Build

Development build:

```bash
docker build \
  -t qwenpaw-all-in-one-hfs:dev \
  .
```

Release-style build:

```bash
docker build \
  -t qwenpaw-all-in-one-hfs:release \
  --build-arg BASE_IMAGE_REF='node:22-slim@sha256:6c74791e557ce11fc957704f6d4fe134a7bc8d6f5ca4403205b2966bd488f6b3' \
  --build-arg QWENPAW_SOURCE_REF='ab814123c59f18b6045ff0204bf2ec5fb31fd598' \
  --build-arg QWENPAW_SOURCE_VERSION='2.0.1' \
  --build-arg QWENPAW_CONSOLE_BUNDLE_URL='https://github.com/BlueSkyXN/QwenPaw-all-in-one-HFS/releases/download/qwenpaw-console-ab814123/qwenpaw-console-ab814123c59f18b6045ff0204bf2ec5fb31fd598.tar.gz' \
  --build-arg QWENPAW_CONSOLE_BUNDLE_SHA256='ce5cc067101ea505ce89664d15a1b757124eeac22a04b273ccc7c016d7b22c66' \
  --build-arg UV_VERSION='0.7.20' \
  .
```

The default build fetches immutable upstream QwenPaw commit `ab814123c59f18b6045ff0204bf2ec5fb31fd598`, validates that `src/qwenpaw/__version__.py` reports `2.0.1`, verifies and extracts the console artifact built from that exact commit, and installs QwenPaw from the fetched source tree. The console artifact is built in GitHub Actions because the QwenPaw 2.0.1 local Monaco bundle exceeds the Hugging Face build worker memory limit. Release validation checks both the source pin and downloaded artifact; `--require-upstream-main` additionally requires the pin to equal live upstream `main`.

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
/nginx-health   Nginx process liveness
/healthz        QwenPaw TCP/process liveness
/readyz         QwenPaw core-agent readiness via /api/healthz; later background work may continue
```

Protected read-only diagnostics:

```text
/_ops/health
/_ops/healthz
/_ops/readyz
/_ops/status
/_ops/system
/_ops/persistence
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
After successful token validation, the service sets a signed HttpOnly cookie for `/_ops/` and redirects to a URL without the token query string.

## Admin Surface

`/_admin` is disabled by default and returns `404` unless explicitly enabled:

```env
ADMIN_ENABLED=true
ADMIN_TOKEN=<strong-random-token>
ADMIN_CSRF_TOKEN=<strong-random-csrf-token>
```

Mutating API calls require token authentication, `X-CSRF-Token: <ADMIN_CSRF_TOKEN>` and `confirm=true`. Supported actions are intentionally narrow:

```text
GET  /_admin/api/status
GET  /_admin/api/actions
GET  /_admin/api/audit?limit=50
POST /_admin/api/actions/restart-service
POST /_admin/api/actions/reload-nginx
POST /_admin/api/actions/run-health-checks
```

## Validation

```bash
bash scripts/static-check.sh
bash scripts/validate-hfs-contract.sh
```

The static gate checks repository shape and Python/shell syntax only. It does not replace Docker build, Hugging Face runtime takeover or live endpoint smoke.

For a running local container, also verify the default admin boundary:

```bash
ADMIN_EXPECTED_ENABLED=false bash scripts/admin-smoke.sh http://127.0.0.1:7860
```

For a deployed Space, run:

```bash
set -a
. ./.env.local
set +a
bash scripts/hf-space-smoke.sh "$SMOKE_BASE_URL"
```

After pushing to both remotes, verify all three states independently:

```text
local HEAD == origin/main == hf/main
Hugging Face repo sha == local HEAD
Hugging Face runtime.raw.sha == local HEAD and runtime.stage == RUNNING
```

Only then treat the Space as updated.

## Production Boundary

This is an HFS demo / personal deployment package. It is not a high-availability production architecture. For sensitive use, keep the Space private/protected, enable authentication, configure strong tokens and review `docs/security.md`.
