# Configuration

Configuration is split into four surfaces:

- Docker build args, which select and pin the upstream source tree.
- Hugging Face Space Variables, which are safe runtime defaults.
- Hugging Face Space Secrets, which are sensitive runtime values.
- Local `.env.local`, which records deployment metadata and private smoke/login values for maintainers.

## Build Args

| Name | Purpose | Release rule |
| --- | --- | --- |
| `BASE_IMAGE_REF` | Base image | Pin digest for release; mutable tag is acceptable only during development |
| `QWENPAW_SOURCE_REPO` | Upstream QwenPaw Git repository fetched during Docker build | Required |
| `QWENPAW_SOURCE_REF` | Upstream QwenPaw commit installed from source | Required; release builds must use a full commit SHA |
| `QWENPAW_SOURCE_VERSION` | Expected `qwenpaw.__version__` value in the pinned source tree | Required; change when the upstream source version changes |
| `UV_VERSION` | uv installer version | Pin for release |

Current default source pins:

```text
BASE_IMAGE_REF=node:22-slim@sha256:6c74791e557ce11fc957704f6d4fe134a7bc8d6f5ca4403205b2966bd488f6b3
QWENPAW_SOURCE_REPO=https://github.com/agentscope-ai/QwenPaw.git
QWENPAW_SOURCE_REF=6815e51d7199939bb199735f6b99fe02d2fa1b2b
QWENPAW_SOURCE_VERSION=2.0.0.post2
UV_VERSION=0.7.20
```

The source ref is an immutable snapshot of upstream `main`. Use `python3 scripts/check-qwenpaw-pins.py --require-upstream-main` when a release must track the current live `main` head; the package version alone cannot distinguish later commits that retain the same version string.

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

The entrypoint manages the persisted QwenPaw JSON field `security.trusted_proxies` directly because it is not a runtime environment variable. It preserves existing proxy networks and adds `127.0.0.1/32` when needed; the automatic migration never adds a broader network.

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
