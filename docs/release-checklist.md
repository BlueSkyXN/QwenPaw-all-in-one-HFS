# Release Checklist

Use this checklist when changing runtime behavior, release pins, deployment docs or anything that affects the Hugging Face Space. For docs-only changes, the Docker build steps may be delegated to GitHub Actions/Hugging Face, but the final closeout still needs both remotes and live runtime state.

## Static

```bash
bash scripts/static-check.sh
bash scripts/validate-hfs-contract.sh
git diff --check
```

For release pin changes, also run the networked check:

```bash
python3 scripts/check-qwenpaw-pins.py --require-upstream-main
```

Before upgrading across an upstream release that migrates persisted configuration, copy
the working directory to a private path in the same Storage Bucket. Keep the bucket ID
and backup path in the local deployment ledger, not in Git:

```bash
RELEASE_BACKUP_ID="pre-upgrade-$(date -u +%Y%m%dT%H%M%SZ)"
hf buckets cp \
  "hf://buckets/$HF_STORAGE_BUCKET/qwenpaw/working/" \
  "hf://buckets/$HF_STORAGE_BUCKET/qwenpaw/backups/$RELEASE_BACKUP_ID/working/"
```

QwenPaw 2.0.1 performs a one-time channel display configuration migration on first load
and may rewrite `config.json` and agent `agent.json` files. Preserve the pre-upgrade copy
until login, existing agents/channels, persistence, logs, and a restart have been verified.

## Release Pins

Record:

```text
BASE_IMAGE_REF=node:22-slim@sha256:6c74791e557ce11fc957704f6d4fe134a7bc8d6f5ca4403205b2966bd488f6b3
QWENPAW_SOURCE_REPO=https://github.com/agentscope-ai/QwenPaw.git
QWENPAW_SOURCE_REF=ab814123c59f18b6045ff0204bf2ec5fb31fd598
QWENPAW_SOURCE_VERSION=2.0.1
UV_VERSION=0.7.20
```

## Build

```bash
docker build \
  --build-arg BASE_IMAGE_REF='node:22-slim@sha256:6c74791e557ce11fc957704f6d4fe134a7bc8d6f5ca4403205b2966bd488f6b3' \
  --build-arg QWENPAW_SOURCE_REF='ab814123c59f18b6045ff0204bf2ec5fb31fd598' \
  --build-arg QWENPAW_SOURCE_VERSION='2.0.1' \
  --build-arg UV_VERSION='0.7.20' \
  -t qwenpaw-all-in-one-hfs:release .
```

## Local Smoke

```bash
docker run -d \
  --name qwenpaw-hfs-release \
  -p 7860:7860 \
  -v qwenpaw-hfs-release-data:/data \
  -e OPS_TOKEN=release-smoke-token \
  -e QWENPAW_AUTH_ENABLED=true \
  qwenpaw-all-in-one-hfs:release

OPS_TOKEN=release-smoke-token bash scripts/hf-space-smoke.sh http://127.0.0.1:7860
```

## Persistence Drill

```bash
docker exec qwenpaw-hfs-release test -f /data/qwenpaw/working/config.json
docker restart qwenpaw-hfs-release
docker exec qwenpaw-hfs-release test -f /data/qwenpaw/working/config.json
```

## Live Space

- Confirm Space build succeeded.
- Confirm runtime takeover completed.
- Confirm `hf spaces volumes list <space-id> --json` reports a read-write Storage Bucket
  mounted at `/data`.
- Run live smoke.
- Confirm `/_ops/version` reports expected release pins.
- Confirm `/readyz` reports upstream QwenPaw core-agent readiness, not only an open TCP port; verify a real app/API path after later background startup work settles.
- When auth is enabled and a user exists, confirm an unauthenticated protected `/api/*` request returns `401`.
- Confirm admin is disabled unless intentionally enabled.

For a live persistence drill, record the bucket-side config object, restart the Space,
and compare it after takeover:

```bash
hf buckets list "$HF_STORAGE_BUCKET/qwenpaw/working/config.json" --json
hf spaces restart "$HF_SPACE_ID"
hf spaces wait "$HF_SPACE_ID" --timeout 15m
hf buckets list "$HF_STORAGE_BUCKET/qwenpaw/working/config.json" --json
bash scripts/hf-space-smoke.sh "$SMOKE_BASE_URL"
```

Repeat the readback after a release rebuild. A stable config object plus
`has_users=true` after restart/rebuild is stronger persistence evidence than a merely
writable `/data` directory.

## GitHub/Hugging Face Closeout

Before pushing:

```bash
git status --short --branch
git check-ignore -v .env.local local/ .DS_Store
```

Commit only tracked public files. Do not stage `.env.local`, `local/`, runtime data, logs or screenshots.

Push:

```bash
git push origin main
git push hf main
```

Confirm remote heads:

```bash
git rev-parse HEAD
git ls-remote origin refs/heads/main
git ls-remote hf refs/heads/main
```

Confirm GitHub Actions:

```bash
gh run list --repo BlueSkyXN/QwenPaw-all-in-one-HFS --branch main --limit 5
```

Confirm Hugging Face runtime:

```bash
hf spaces info BlueSkyXN/QwenPaw-all-in-one-HFS --json
```

Done means:

```text
HEAD == origin/main == hf/main
GitHub static-check succeeded for HEAD
Hugging Face repo sha == HEAD
Hugging Face runtime.raw.sha == HEAD
Hugging Face runtime.stage == RUNNING
Storage Bucket is mounted read-write at /data
live smoke passed
worktree has no uncommitted tracked changes
```

## Browser Login Check

For fresh deployments, verify first-account creation in a browser:

```text
/login?redirect=%2F shows Create Account
registration succeeds with local-only .env.local test credentials
the app redirects to /chat
Logout is visible
browser console has no warn/error entries relevant to the app
```

Keep the username/password and screenshots local-only.
