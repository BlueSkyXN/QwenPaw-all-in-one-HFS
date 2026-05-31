# Security

QwenPaw may contain personal memory, files, provider credentials and channel tokens. Deploy as a private/protected Space unless you have independently reviewed all auth boundaries.

## Defaults

- `/_ops` protected endpoints require `OPS_TOKEN`.
- `/_admin` is disabled by default.
- `/_ops/config` returns only safe config and secret presence booleans.
- `.dockerignore` excludes common secret and local runtime files.
- `QWENPAW_TELEMETRY_OPT_OUT=1` is the HFS default so first-run init does not upload telemetry from the Space.

## Admin Surface

When `ADMIN_ENABLED=true`, mutating endpoints still require:

- `ADMIN_TOKEN`
- `ADMIN_CSRF_TOKEN`
- JSON body with `confirm=true`
- fixed whitelisted actions only
- audit logging to `/data/var/logs/admin-audit.jsonl`

Current whitelisted actions:

```text
restart-service: qwenpaw, nginx, ops-service, admin-service, xvfb
reload-nginx
run-health-checks
```

## What Not To Commit

```text
.env
.env.local
*.secret
*.key
*.pem
*.sqlite
*.db
logs/
data/
local/
```
