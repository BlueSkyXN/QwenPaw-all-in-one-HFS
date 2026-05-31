# Configuration

## Build Args

| Name | Purpose | Release rule |
| --- | --- | --- |
| `BASE_IMAGE_REF` | Base image | Pin digest for release |
| `QWENPAW_VERSION` | QwenPaw package version | Required |
| `QWENPAW_PACKAGE_SHA256` | QwenPaw package artifact hash | Required for release |
| `UV_VERSION` | uv installer version | Pin for release |
| `QWENPAW_UPSTREAM_REF` | Upstream QwenPaw commit/tag metadata | Record for audit |

## Runtime Variables

| Name | Default | Purpose |
| --- | --- | --- |
| `PORT` | `7860` | Public Nginx port |
| `QWENPAW_PORT` | `8088` | Internal QwenPaw port |
| `QWENPAW_WORKING_DIR` | `/data/qwenpaw/working` | QwenPaw working state |
| `QWENPAW_SECRET_DIR` | `/data/qwenpaw/secrets` | Local secrets/config |
| `QWENPAW_BACKUP_DIR` | `/data/qwenpaw/backups` | Backups |
| `QWENPAW_DISABLED_CHANNELS` | `imessage` | Channel exclusion list |
| `QWENPAW_AUTH_ENABLED` | unset | Enable QwenPaw auth per upstream behavior |
| `QWENPAW_TELEMETRY_OPT_OUT` | `1` | Write QwenPaw telemetry opt-out marker before first init |
| `ADMIN_ENABLED` | `false` | Enable admin surface |

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

Do not commit `.env.local`, key files, database files or logs.
