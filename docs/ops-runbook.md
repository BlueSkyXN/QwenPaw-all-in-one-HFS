# Ops Runbook

Use this runbook after the Space has built or when a live smoke check fails. Prefer `X-Ops-Token` headers for scripted calls.

## Health Endpoints

```text
/nginx-health       Nginx liveness
/healthz            comprehensive health
/readyz             readiness
/_ops/health        protected health alias
/_ops/healthz       protected comprehensive health
/_ops/readyz        protected readiness
/_ops/status        Supervisor process status
/_ops/system        safe system summary
/_ops/config        safe config summary
/_ops/version       build pins and runtime metadata
/_ops/logs          whitelisted log tail
/_ops/errors        recent error-pattern summary
/_ops/metrics       Prometheus-style text metrics
```

Protected endpoints require:

```text
X-Ops-Token: <OPS_TOKEN>
Authorization: Bearer <OPS_TOKEN>
```

## Standard Triage

Load local smoke values:

```bash
set -a
. ./.env.local
set +a
```

Check public health:

```bash
curl -fsS "$SMOKE_BASE_URL/nginx-health"
curl -fsS "$SMOKE_BASE_URL/healthz"
curl -fsS "$SMOKE_BASE_URL/readyz"
```

Check protected status:

```bash
curl -fsS -H "X-Ops-Token: $OPS_TOKEN" "$SMOKE_BASE_URL/_ops/status"
curl -fsS -H "X-Ops-Token: $OPS_TOKEN" "$SMOKE_BASE_URL/_ops/version"
curl -fsS -H "X-Ops-Token: $OPS_TOKEN" "$SMOKE_BASE_URL/_ops/config"
```

Inspect logs:

```bash
curl -fsS -H "X-Ops-Token: $OPS_TOKEN" "$SMOKE_BASE_URL/_ops/logs?service=qwenpaw-err&limit=200"
curl -fsS -H "X-Ops-Token: $OPS_TOKEN" "$SMOKE_BASE_URL/_ops/errors"
```

Allowed log service names:

```text
qwenpaw
qwenpaw-err
nginx
nginx-err
nginx-access
nginx-error
ops-service
ops-service-err
admin-service
admin-service-err
xvfb
xvfb-err
supervisord
```

## Common Failures

### Space repo SHA changed but app still looks old

Check:

```bash
hf spaces info BlueSkyXN/QwenPaw-all-in-one-HFS --json
```

Compare `sha` and `runtime.raw.sha` with local `git rev-parse HEAD`. The Space repo can update before runtime takeover. Wait for `runtime.stage=RUNNING` and `runtime.raw.sha == HEAD`.

### `/healthz` returns 503

Check:

```bash
curl -H "X-Ops-Token: $OPS_TOKEN" https://space/_ops/status
curl -H "X-Ops-Token: $OPS_TOKEN" https://space/_ops/logs?service=qwenpaw
```

### QwenPaw did not initialize

Confirm `/data/qwenpaw/working/config.json` exists. If it does not, inspect `qwenpaw.err.log`.

```bash
curl -fsS -H "X-Ops-Token: $OPS_TOKEN" "$SMOKE_BASE_URL/_ops/logs?service=qwenpaw-err&limit=200"
```

### Persistent data is missing after restart

Persistent Storage may not be enabled. The runtime writes `/data/.qwenpaw_hfs_persistent_storage_probe` when `/data` is writable.

### Browser-related skills fail

Inspect `xvfb.err.log` and confirm Chromium exists at `/usr/bin/chromium`.

### First admin account page appears again

This usually means the Space is using a fresh or lost `/data` volume. Confirm Persistent Storage and check whether `/data/qwenpaw/working/config.json` exists. Do not create a new account unless the deployment is intentionally fresh.

### `/_admin/` returns 404

This is the default safe state. `scripts/hf-space-smoke.sh` treats `401`, `403` or `404` as acceptable admin boundary responses. Enable admin only for explicit maintenance windows.
