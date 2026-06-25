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
  ├─ builds console frontend assets
  ├─ copies console/dist into src/qwenpaw/console
  ├─ installs QwenPaw from the fetched source tree
  └─ copies docker/ runtime glue
```

The current pinned source is QwenPaw commit `25015cb5e36fc7a4067d19c6d11ced2c1fe1f4e0` with source version `2.0.0b1`.

## Persistence Boundary

```text
/data/qwenpaw/working
/data/qwenpaw/secrets
/data/qwenpaw/backups
/data/var/logs
```

Transient runtime files use `/tmp/qwenpaw-run`.

`/data/qwenpaw/working/config.json` is the first-run boundary. If it is missing, `docker/entrypoint.sh` runs:

```text
qwenpaw init --defaults --accept-security
```

Hugging Face rebuilds should not depend on `/data` during Docker build. `/data` only becomes meaningful at runtime.

## Ops/Admin Boundary

`/_ops` is read-only and never runs request-supplied commands. Fixed local checks are whitelisted in code.

`/_admin` is disabled by default. When enabled, mutating actions require token authentication, `X-CSRF-Token` and `confirm=true`.

## Request Routing

Nginx owns the public port and forwards:

```text
/                  -> QwenPaw web app
/nginx-health      -> direct Nginx response
/healthz, /readyz  -> ops-service health/readiness
/_ops/*            -> ops-service protected diagnostics
/_admin/*          -> admin-service boundary
```

This keeps Hugging Face's single public port model while still allowing separate internal services for diagnostics and maintenance.
