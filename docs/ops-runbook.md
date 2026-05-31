# Ops Runbook

## Health Endpoints

```text
/nginx-health       Nginx liveness
/healthz            comprehensive health
/readyz             readiness
/_ops/health        protected health alias
/_ops/status        Supervisor process status
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

## Common Failures

### `/healthz` returns 503

Check:

```bash
curl -H "X-Ops-Token: $OPS_TOKEN" https://space/_ops/status
curl -H "X-Ops-Token: $OPS_TOKEN" https://space/_ops/logs?service=qwenpaw
```

### QwenPaw did not initialize

Confirm `/data/qwenpaw/working/config.json` exists. If it does not, inspect `qwenpaw.err.log`.

### Persistent data is missing after restart

Persistent Storage may not be enabled. The runtime writes `/data/.qwenpaw_hfs_persistent_storage_probe` when `/data` is writable.

### Browser-related skills fail

Inspect `xvfb.err.log` and confirm Chromium exists at `/usr/bin/chromium`.
