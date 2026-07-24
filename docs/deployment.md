# Deployment

This repository is deployed as a repo-root Hugging Face Docker Space. GitHub and Hugging Face are two independent remotes; a complete deployment verifies both git state and live runtime state.

## Prerequisites

- Hugging Face Space SDK: Docker.
- A private Hugging Face Storage Bucket attached read-write at `/data` before relying
  on runtime state.
- `OPS_TOKEN` configured in Space Settings for protected diagnostics.
- QwenPaw authentication enabled for exposed deployments.

Recommended local ledger:

```bash
cp .env.example .env.local
```

Fill `GH_REPO`, `HF_SPACE_ID`, `SMOKE_BASE_URL` and `OPS_TOKEN` in `.env.local`. Keep real values local-only.

## Lightweight Local Checks

These checks do not install external dependencies and do not build the container:

```bash
bash scripts/static-check.sh
bash scripts/validate-hfs-contract.sh
git diff --check
```

## Local Build

Local Docker build is optional for development. For this repository's normal maintenance workflow, heavy build/runtime verification can be performed by GitHub Actions and Hugging Face runtime instead.

```bash
bash scripts/local-build.sh
```

or:

```bash
docker build \
  -t qwenpaw-all-in-one-hfs:dev \
  --build-arg QWENPAW_SOURCE_REF=ab814123c59f18b6045ff0204bf2ec5fb31fd598 \
  --build-arg QWENPAW_SOURCE_VERSION=2.0.1 \
  --build-arg QWENPAW_CONSOLE_BUNDLE_URL=https://github.com/BlueSkyXN/QwenPaw-all-in-one-HFS/releases/download/qwenpaw-console-ab814123/qwenpaw-console-ab814123c59f18b6045ff0204bf2ec5fb31fd598.tar.gz \
  --build-arg QWENPAW_CONSOLE_BUNDLE_SHA256=ce5cc067101ea505ce89664d15a1b757124eeac22a04b273ccc7c016d7b22c66 \
  .
```

## Local Run

```bash
OPS_TOKEN=dev-ops-token bash scripts/local-run.sh
```

Then open:

```text
http://127.0.0.1:7860/
```

## Smoke

```bash
OPS_TOKEN=dev-ops-token bash scripts/hf-space-smoke.sh http://127.0.0.1:7860
```

## Hugging Face Storage Bucket

Current Hugging Face guidance uses Storage Bucket volumes for durable Space data. The
legacy `small`/`medium`/`large` Space storage API is deprecated in current
`huggingface_hub`; do not use it for a new deployment.

Create a private bucket within the account's existing storage allowance:

```bash
hf buckets create <namespace>/<bucket-name> --private --exist-ok
```

Attach it read-write at `/data`:

```bash
hf spaces volumes set <namespace>/<space-name> \
  -v hf://buckets/<namespace>/<bucket-name>:/data
hf spaces wait <namespace>/<space-name> --timeout 15m
hf spaces volumes list <namespace>/<space-name> --json
```

The expected volume has `type=bucket`, `mount_path=/data` and `read_only=false`.
`hf spaces volumes set` replaces the complete volume list, so include every existing
mount in the command instead of accidentally dropping unrelated volumes.

Record the bucket ID only in local `.env.local` or another private deployment ledger:

```env
HF_STORAGE_BUCKET=<namespace>/<bucket-name>
```

## Hugging Face Space

1. Create a Docker Space.
2. Push this repository root to the Space repository.
3. Attach a private Storage Bucket read-write at `/data` if runtime data must survive
   restarts/rebuilds.
4. Set Variables/Secrets from `docs/configuration.md`.
5. Wait for build and runtime takeover.
6. Run smoke against the live Space URL.

GitHub push, HF Space repo SHA, runtime takeover and endpoint smoke are separate states. Treat the Space as available only after live smoke passes.

## Push Flow

Expected remotes:

```bash
git remote -v
```

```text
origin  https://github.com/BlueSkyXN/QwenPaw-all-in-one-HFS.git
hf      https://huggingface.co/spaces/BlueSkyXN/QwenPaw-all-in-one-HFS
```

Push both remotes:

```bash
git push origin main
git push hf main
```

Confirm branch heads:

```bash
git rev-parse HEAD
git ls-remote origin refs/heads/main
git ls-remote hf refs/heads/main
```

All three SHAs must match.

## Runtime Takeover

After `git push hf main`, the Space repository `sha` can update before the running container does. Check runtime takeover explicitly:

```bash
hf spaces info BlueSkyXN/QwenPaw-all-in-one-HFS --json
```

Deployment is not complete until:

```text
repo sha == HEAD
runtime.stage == RUNNING
runtime.raw.sha == HEAD
```

`RUNNING_BUILDING` and `RUNNING_APP_STARTING` are transitional states. Keep polling until `RUNNING` and the runtime SHA has switched.

## Live Smoke

```bash
set -a
. ./.env.local
set +a
bash scripts/hf-space-smoke.sh "$SMOKE_BASE_URL"
```

Expected checks:

```text
PASS smoke: nginx-health
PASS smoke: healthz
PASS smoke: readyz
PASS smoke: web-root
PASS smoke: qwenpaw-auth-boundary status=401
PASS smoke: ops-health
PASS smoke: ops-readyz
PASS smoke: ops-status
PASS smoke: ops-config
PASS smoke: ops-persistence
PASS smoke: ops-version
PASS smoke: admin default boundary status=404
PASS qwenpaw-hfs-smoke
```

The QwenPaw auth-boundary assertion runs when authentication is enabled and a user already exists. On a fresh volume it reports a warning until first-account registration is complete.

## First-Run Browser Verification

On a fresh attached `/data` volume, QwenPaw shows `Create Account`. Use the browser to
create the first admin account only with credentials stored in local `.env.local`:

```env
QWENPAW_ADMIN_USERNAME=<local-test-admin-name>
QWENPAW_ADMIN_PASSWORD=<local-test-admin-password>
```

Successful verification reaches `/chat` and shows `Logout`. Store screenshots under `local/`; they are local-only and ignored.

If the page already has an account, use the existing deployment credential record. Do not reset or overwrite persistent QwenPaw data unless that is an explicit maintenance task.
