# Configuration

Configuration is split into four surfaces:

- Docker build args, which select and pin the upstream package artifact.
- Hugging Face Space Variables, which are safe runtime defaults.
- Hugging Face Space Secrets, which are sensitive runtime values.
- Local `.env.local`, which records deployment metadata and private smoke/login values for maintainers.

## Build Args

| Name | Purpose | Release rule |
| --- | --- | --- |
| `BASE_IMAGE_REF` | Base image | Pin digest for release; mutable tag is acceptable only during development |
| `QWENPAW_VERSION` | QwenPaw package version installed during Docker build | Required |
| `QWENPAW_PACKAGE_SHA256` | SHA256 of the selected QwenPaw package artifact | Required for release; changing `QWENPAW_VERSION` requires changing this too |
| `UV_VERSION` | uv installer version | Pin for release |
| `QWENPAW_UPSTREAM_REF` | Upstream QwenPaw commit/tag metadata | Record for audit; does not fetch source in this runtime mode |

Current default release pins:

```text
QWENPAW_VERSION=1.1.12.post2
QWENPAW_PACKAGE_SHA256=c07ba7780d0752281138298a6e2a7b0efd372bffab60e68d1d7e9856a5b16e6a
UV_VERSION=0.7.20
QWENPAW_UPSTREAM_REF=09fc515c88a5e817870e6b975e66b5be81893e03
```

## Runtime Variables

| Name | Default | Purpose |
| --- | --- | --- |
| `PORT` | `7860` | Public Nginx port |
| `QWENPAW_PORT` | `8088` | Internal QwenPaw port |
| `QWENPAW_WORKING_DIR` | `/data/qwenpaw/working` | QwenPaw working state |
| `QWENPAW_SECRET_DIR` | `/data/qwenpaw/secrets` | Local secrets/config |
| `QWENPAW_BACKUP_DIR` | `/data/qwenpaw/backups` | Backups |
| `QWENPAW_DISABLED_CHANNELS` | `imessage` | Channel exclusion list |
| `QWENPAW_AUTH_ENABLED` | unset | Enable QwenPaw auth per upstream behavior; recommended `true` on Hugging Face |
| `QWENPAW_TELEMETRY_OPT_OUT` | `1` | Write QwenPaw telemetry opt-out marker before first init |
| `ADMIN_ENABLED` | `false` | Enable admin surface |
| `QWENPAW_OPS_PORT` | `8081` | Internal ops-service port |
| `QWENPAW_ADMIN_PORT` | `8082` | Internal admin-service port |
| `QWENPAW_OPS_LOG_DIR` | `/data/var/logs` | Log directory used by `/_ops/logs` |
| `QWENPAW_ADMIN_AUDIT_LOG` | `/data/var/logs/admin-audit.jsonl` | Admin action audit log |
| `OPS_SESSION_TTL_SECONDS` | `3600` | Signed browser session lifetime for `/_ops/` query-token migration |
| `OPS_COOKIE_SECURE` | `auto` | Add `Secure` to `/_ops/` session cookies when forced or when `X-Forwarded-Proto=https` |

Recommended Hugging Face Variables:

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

## Secrets

Set these via Hugging Face Space Settings or local environment only:

```env
OPS_TOKEN=<required for protected /_ops endpoints>
ADMIN_TOKEN=<required if ADMIN_ENABLED=true>
ADMIN_CSRF_TOKEN=<required for admin mutating endpoints if ADMIN_ENABLED=true>
DASHSCOPE_API_KEY=<optional>
OPENAI_API_KEY=<optional>
GEMINI_API_KEY=<optional>
TELEGRAM_BOT_TOKEN=<optional>
DISCORD_BOT_TOKEN=<optional>
```

`OPS_TOKEN` protects direct `/_ops/*` diagnostics including `/_ops/health`, `/_ops/healthz`, `/_ops/readyz`, `/_ops/status`, `/_ops/system`, `/_ops/persistence`, `/_ops/config`, `/_ops/version`, `/_ops/logs`, `/_ops/errors`, `/_ops/metrics` and browser diagnostics at `/_ops/?token=...`.

Prefer `X-Ops-Token` or `Authorization: Bearer` for scripts. The query token form is only for manual browser diagnostics; after validation it sets a signed HttpOnly cookie scoped to `/_ops/` and redirects to a URL without the token query string.

## Local `.env.local` Ledger

`.env.local` is for machine-local deployment records and smoke credentials. It is ignored by git and Docker build context.

Suggested non-secret metadata:

```env
GH_REPO=BlueSkyXN/QwenPaw-all-in-one-HFS
HF_SPACE_ID=BlueSkyXN/QwenPaw-all-in-one-HFS
HF_SPACE_URL=https://huggingface.co/spaces/BlueSkyXN/QwenPaw-all-in-one-HFS
HF_PUBLIC_URL=https://blueskyxn-qwenpaw-all-in-one-hfs.hf.space
SMOKE_BASE_URL=https://blueskyxn-qwenpaw-all-in-one-hfs.hf.space
```

Suggested local-only secrets and test records:

```env
OPS_TOKEN=<same value configured in Hugging Face Space Settings>
ADMIN_TOKEN=<only when ADMIN_ENABLED=true>
ADMIN_CSRF_TOKEN=<only when ADMIN_ENABLED=true>
ADMIN_EXPECTED_ENABLED=<true only for admin smoke>
ADMIN_SMOKE_ACTIONS=<true only when run-health-checks should execute>
QWENPAW_ADMIN_USERNAME=<first-run browser test username>
QWENPAW_ADMIN_PASSWORD=<first-run browser test password>
```

Do not commit `.env.local`, key files, database files, screenshots, runtime exports or logs.
