# Release Checklist

Use this checklist only for an explicitly approved release operation that changes runtime behavior, build pins, deployment docs, or the Hugging Face Space. A semantic-manifest or documentation change is complete locally after static validation; remote publication, Space takeover, and live runtime verification are subsequent independent gates.

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

For a candidate repository release, first commit the reviewed change and verify the exact
clean commit locally without contacting Hugging Face:

```bash
source_ref=$(git rev-parse HEAD)
bundle_dir=$(mktemp -d)
test -z "$(git status --porcelain=v1 --untracked-files=all)"
python3 scripts/export_space_bundle.py export \
  --source-commit "$source_ref" \
  --manifest hfs-dev.candidate.toml \
  --output "$bundle_dir"
python3 scripts/export_space_bundle.py verify --bundle "$bundle_dir"
```

Record the complete `BUILD_SOURCE.json` and `SHA256SUMS` readback as repository evidence;
do not treat either as runtime evidence.

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

If the pinned upstream console exceeds the Hugging Face build worker memory limit, build
the exact source commit with the manual GitHub Actions `build-console-bundle` workflow.
Download its short-lived bundle, verify the generated checksum, then publish it as an
immutable companion release asset before adding its URL and checksum to the Dockerfile build
pins. Do not substitute a bundle built from a tag or a different commit. This paired bundle
does not change the HFS `source` lane to an `artifact` lane.

## Release Pins

Record:

```text
BASE_IMAGE_REF=node:22-slim@sha256:6c74791e557ce11fc957704f6d4fe134a7bc8d6f5ca4403205b2966bd488f6b3
QWENPAW_SOURCE_REPO=https://github.com/agentscope-ai/QwenPaw.git
QWENPAW_SOURCE_REF=734c8b9fa610381fa6d79b10ae3641b6db4a8cb2
QWENPAW_SOURCE_VERSION=2.0.1
QWENPAW_CONSOLE_BUNDLE_URL=https://github.com/BlueSkyXN/QwenPaw-all-in-one-HFS/releases/download/qwenpaw-console-734c8b9f/qwenpaw-console-734c8b9fa610381fa6d79b10ae3641b6db4a8cb2.tar.gz
QWENPAW_CONSOLE_BUNDLE_SHA256=c1bbaa54f7f07411b5948c2984c054c0e20352f46f6406101db65a9188aeb8cf
UV_VERSION=0.7.20
```

## Build

```bash
docker build \
  --build-arg BASE_IMAGE_REF='node:22-slim@sha256:6c74791e557ce11fc957704f6d4fe134a7bc8d6f5ca4403205b2966bd488f6b3' \
  --build-arg QWENPAW_SOURCE_REF='734c8b9fa610381fa6d79b10ae3641b6db4a8cb2' \
  --build-arg QWENPAW_SOURCE_VERSION='2.0.1' \
  --build-arg QWENPAW_CONSOLE_BUNDLE_URL='https://github.com/BlueSkyXN/QwenPaw-all-in-one-HFS/releases/download/qwenpaw-console-734c8b9f/qwenpaw-console-734c8b9fa610381fa6d79b10ae3641b6db4a8cb2.tar.gz' \
  --build-arg QWENPAW_CONSOLE_BUNDLE_SHA256='c1bbaa54f7f07411b5948c2984c054c0e20352f46f6406101db65a9188aeb8cf' \
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

## Candidate GitHub Actions Gate

The manual `deploy-hf-space-candidate` workflow is the only reviewed candidate repository
upload path. Before dispatch:

- Confirm the workflow ref is GitHub `main` and record its exact 40-character SHA.
- Confirm the fixed candidate `BlueSkyXN/QwenPaw-all-in-one-HFS-v2-candidate` already exists and is private.
- Confirm the `hfs-candidate` GitHub environment exposes only the required deployment Secret name `HF_TOKEN`; never print its value.
- Review candidate Settings separately with `hf_space_sync.py diff`; repo upload does not sync Settings.
- Enter `source_ref=<exact main SHA>` and `confirm_upload=PUBLISH_CANDIDATE`.

The workflow must fail closed if `source_ref`, `GITHUB_SHA`, or current `origin/main` differ;
if static checks or bundle verification fail; if the Space is not private; or if the remote
repository contains a path outside the bundle allowlist. It never deletes remote files.

After a green workflow, record these as separate states:

```text
GitHub main SHA == exported BUILD_SOURCE.wrapper_source_commit
candidate remote path set == exporter path allowlist
candidate remote SHA256SUMS == local verified SHA256SUMS
complete downloaded bundle passes exporter verify
runtime takeover: NOT PROVEN by this workflow
live/auth smoke: NOT RUN by this workflow
persistence/restart/backup/restore: NOT RUN by this workflow
```

Only after separately approved runtime checks may the candidate be described as deployed
and accepted. A successful repository upload/readback alone is a publish result.

## GitHub/Hugging Face Closeout

This direct two-remote closeout applies to the canonical Preview Space. Do not push the GitHub root
directly to the candidate Space.

Before pushing:

```bash
git status --short --branch
git check-ignore -v .env .env.local config.toml local/ .DS_Store
```

Commit only tracked public files. Do not stage `.env`, `.env.local`, `config.toml`, `local/`, runtime data, logs or screenshots.

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

For fresh deployments, verify first-account creation in a browser using local values from `.env` (or the ignored `.env.local` compatibility file):

```text
/login?redirect=%2F shows Create Account
registration succeeds with local-only .env test credentials
the app redirects to /chat
Logout is visible
browser console has no warn/error entries relevant to the app
```

Keep the username/password and screenshots local-only.
