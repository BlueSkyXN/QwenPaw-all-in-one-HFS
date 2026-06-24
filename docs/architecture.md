# Architecture

QwenPaw is served as a multi-process Docker Space behind one public Nginx port. The upstream package is installed at build time; this repository provides the runtime glue around it.

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

## Build-Time Artifact Flow

```text
Docker build
  ├─ starts from BASE_IMAGE_REF
  ├─ installs OS/runtime packages
  ├─ installs uv
  ├─ downloads qwenpaw==QWENPAW_VERSION
  ├─ verifies QWENPAW_PACKAGE_SHA256
  └─ copies docker/ runtime glue
```

`QWENPAW_UPSTREAM_REF` is audit metadata in this runtime mode. If future runtime behavior requires building from upstream source, change the declared runtime mode instead of silently mixing source-fetch into artifact-at-build-time.

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
