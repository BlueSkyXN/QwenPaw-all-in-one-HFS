# Security

QwenPaw may contain personal memory, files, provider credentials and channel tokens. Deploy as a private/protected Space unless you have independently reviewed all auth boundaries.

## Defaults

- `/_ops` protected endpoints require `OPS_TOKEN`.
- `/_admin` is disabled by default.
- `/_ops/config` returns only safe config and secret presence booleans.
- `.dockerignore` excludes common secret and local runtime files.
- `QWENPAW_TELEMETRY_OPT_OUT=1` is the HFS default so first-run init does not upload telemetry from the Space.

## Authentication

Set `QWENPAW_AUTH_ENABLED=true` for exposed Spaces. On a fresh Storage Bucket mounted
at `/data`, the app will create the first admin account through the browser. Treat that
username/password as a real deployment credential:

- Keep it in the local `.env` ledger or a password manager, not in git.
- Do not place it in screenshots, PR descriptions, issue comments or public logs.
- If the `Create Account` screen reappears unexpectedly, confirm the `/data` volume with
  `hf spaces volumes list` before creating another account.

### Reverse Proxy Boundary

Latest QwenPaw only trusts `X-Forwarded-For` and `X-Real-IP` when the direct peer is listed in `security.trusted_proxies`. This Space always places Nginx on `127.0.0.1` in front of QwenPaw, so `docker/prepare_runtime_config.py` atomically adds `127.0.0.1/32` to that persisted list after initialization and on upgrades.

Nginx replaces inbound forwarding headers with `$remote_addr`; it does not append a client-supplied chain. Do not broaden the trusted proxy list to `0.0.0.0/0`, `::/0`, unknown Hugging Face ranges or other networks that have not been independently verified.

When `QWENPAW_AUTH_ENABLED=true` and an account exists, `scripts/hf-space-smoke.sh` verifies that an unauthenticated external request to a protected QwenPaw API returns `401`.

## Ops Surface

`/healthz` and `/readyz` are public aliases for platform health checks. Direct `/_ops/*` endpoints require `OPS_TOKEN`.

Supported token forms:

```text
X-Ops-Token: <OPS_TOKEN>
Authorization: Bearer <OPS_TOKEN>
/_ops/?token=<OPS_TOKEN>
```

Use headers for automation. The query token form is a browser-only fallback and can be recorded in browser history or proxy logs.
When the query token is valid, `ops-service` exchanges it for a signed HttpOnly cookie scoped to `/_ops/` and redirects to a clean URL. Do not place `OPS_TOKEN` in links, screenshots or long-lived docs.

## Admin Surface

When `ADMIN_ENABLED=true`, mutating endpoints still require:

- `ADMIN_TOKEN`
- `ADMIN_CSRF_TOKEN`
- JSON body with `confirm=true`
- fixed whitelisted actions only
- audit logging to `/data/var/logs/admin-audit.jsonl`

Current admin endpoints:

```text
GET  /_admin/api/status
GET  /_admin/api/actions
GET  /_admin/api/audit
POST /_admin/api/actions/restart-service: qwenpaw, nginx, ops-service, admin-service, xvfb
POST /_admin/api/actions/reload-nginx
POST /_admin/api/actions/run-health-checks
```

Leave `ADMIN_ENABLED=false` for normal operation. Enabling admin changes the risk profile because it exposes controlled restart and health-check actions, even though they are whitelisted.
Do not add a shell, arbitrary command runner, package installer, file editor or secret viewer to `/_admin`.

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
