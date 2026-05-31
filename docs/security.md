# Security

QwenPaw may contain personal memory, files, provider credentials and channel tokens. Deploy as a private/protected Space unless you have independently reviewed all auth boundaries.

## Defaults

- `/_ops` protected endpoints require `OPS_TOKEN`.
- `/_admin` is disabled by default.
- `/_ops/config` returns only safe config and secret presence booleans.
- `.dockerignore` excludes common secret and local runtime files.
- `QWENPAW_TELEMETRY_OPT_OUT=1` is the HFS default so first-run init does not upload telemetry from the Space.

## Authentication

Set `QWENPAW_AUTH_ENABLED=true` for exposed Spaces. On a fresh persistent volume the app will create the first admin account through the browser. Treat that username/password as a real deployment credential:

- Keep it in local `.env.local` or a password manager, not in git.
- Do not place it in screenshots, PR descriptions, issue comments or public logs.
- If the `Create Account` screen reappears unexpectedly, investigate `/data` persistence before creating another account.

## Ops Surface

`/_ops/healthz` and `/_ops/readyz` are public through `/healthz` and `/readyz` for platform health checks. Other `/_ops` endpoints require `OPS_TOKEN`.

Supported token forms:

```text
X-Ops-Token: <OPS_TOKEN>
Authorization: Bearer <OPS_TOKEN>
/_ops/?token=<OPS_TOKEN>
```

Use headers for automation. The query token form is a browser-only fallback and can be recorded in browser history or proxy logs.

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

Leave `ADMIN_ENABLED=false` for normal operation. Enabling admin changes the risk profile because it exposes controlled restart and health-check actions, even though they are whitelisted.

## What Not To Commit

```text
.env
.env.local
.env.* except `.env.example`
*.secret
*.key
*.pem
*.crt
*.p12
*.sqlite
*.db
logs/
data/
local/
.DS_Store
```

Also avoid committing browser screenshots that reveal live account state, provider names, local usernames, file names, prompts, memory contents or tokens.
