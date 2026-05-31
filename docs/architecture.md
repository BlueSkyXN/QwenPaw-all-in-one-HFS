# Architecture

## Process Topology

```text
Nginx :7860
  ├─ /                  -> QwenPaw app :8088
  ├─ /nginx-health      -> static Nginx liveness
  ├─ /healthz           -> ops-service /_ops/healthz
  ├─ /readyz            -> ops-service /_ops/readyz
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

## Persistence Boundary

```text
/data/qwenpaw/working
/data/qwenpaw/secrets
/data/qwenpaw/backups
/data/var/logs
```

Transient runtime files use `/tmp/qwenpaw-run`.

## Ops/Admin Boundary

`/_ops` is read-only and never runs request-supplied commands. Fixed local checks are whitelisted in code.

`/_admin` is disabled by default. When enabled, mutating actions require token authentication and `confirm=true`.
