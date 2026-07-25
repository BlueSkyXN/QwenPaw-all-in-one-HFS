# Architecture

QwenPaw is served as a multi-process Docker Space behind one public Nginx port. The pinned upstream source tree is fetched and installed at build time; this repository provides the runtime glue around it.

## Process Topology

```text
Nginx :7860
  ├─ /                  -> QwenPaw app :8088
  ├─ /nginx-health      -> static Nginx liveness
  ├─ /healthz           -> ops-service public healthz
  ├─ /readyz            -> ops-service public readiness
  ├─ /_ops/*            -> ops-service :8081
  └─ /_admin/*          -> admin-service :8082

Supervisor
  ├─ xvfb
  ├─ qwenpaw
  ├─ nginx
  ├─ ops-service
  └─ admin-service
```

QwenPaw is started with:

```text
dbus-run-session -- qwenpaw app --host 127.0.0.1 --port 8088
```

Xvfb provides a display for browser/desktop capabilities.

## Build-Time Source Flow

```text
Docker build
  ├─ starts from BASE_IMAGE_REF
  ├─ installs OS/runtime packages
  ├─ installs uv
  ├─ fetches QWENPAW_SOURCE_REF from QWENPAW_SOURCE_REPO
  ├─ verifies QWENPAW_SOURCE_VERSION from src/qwenpaw/__version__.py
  ├─ downloads and verifies QWENPAW_CONSOLE_BUNDLE_SHA256
  ├─ extracts the same-commit console bundle into src/qwenpaw/console
  ├─ installs QwenPaw from the fetched source tree
  └─ copies docker/ runtime glue
```

The current pinned source is QwenPaw commit `734c8b9fa610381fa6d79b10ae3641b6db4a8cb2` with source version `2.0.1`. Its console bundle is built from the same commit on a GitHub runner and checksum-verified before the source tree is installed; upstream product source is still fetched rather than vendored.

## Persistence Boundary

```text
/data/qwenpaw/working
/data/qwenpaw/secrets
/data/qwenpaw/backups
/data/var/logs
```

Transient runtime files use `/tmp/qwenpaw-run`.

On Hugging Face Spaces, `/data` is durable only when a Storage Bucket is attached as a
read-write volume at that exact path. The volume attachment is Space configuration,
not part of the Git repository. A writable `/data` directory without an attached
volume is still ephemeral.

`/data/qwenpaw/working/config.json` is the first-run boundary. If it is missing, `docker/entrypoint.sh` runs:

```text
qwenpaw init --defaults --accept-security
```

After initialization, `docker/prepare_runtime_config.py` atomically ensures the persisted config includes the local Nginx reverse proxy at `127.0.0.1/32`, while preserving user-managed proxy entries and never adding a broader network. Nginx overwrites `X-Forwarded-For` and `X-Real-IP` with its direct peer address. This lets latest QwenPaw resolve external requests without treating every Nginx request as loopback and bypassing authentication.

Hugging Face rebuilds should not depend on `/data` during Docker build. `/data` only
becomes meaningful at runtime after the configured Storage Bucket volume is mounted.

## Ops/Admin Boundary

`/_ops` is read-only and never runs request-supplied commands. Fixed local checks are whitelisted in code.

`/_admin` is disabled by default. When enabled, mutating actions require token authentication, `X-CSRF-Token` and `confirm=true`.

## Request Routing

Nginx owns the public port and forwards:

```text
/                  -> QwenPaw web app
/nginx-health      -> direct Nginx response
/healthz           -> ops-service QwenPaw process liveness
/readyz            -> ops-service probe of QwenPaw /api/healthz core-agent readiness
/_ops/*            -> ops-service protected diagnostics
/_admin/*          -> admin-service boundary
```

This keeps Hugging Face's single public port model while still allowing separate internal services for diagnostics and maintenance.
