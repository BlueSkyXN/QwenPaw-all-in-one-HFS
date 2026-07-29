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
cp .env.example .env
```

Fill `.env` from the committed no-secret template. It is the local HFS value ledger for control values, Space Variables, Space Secrets, and smoke inputs; keep real values local-only. `.env.local` remains ignored only for local Docker/run compatibility.

## Lightweight Local Checks

These checks do not install external dependencies and do not build the container:

```bash
bash scripts/static-check.sh
bash scripts/validate-hfs-contract.sh
git diff --check
```

## Candidate Bundle Contract

The candidate Space is fixed at
`BlueSkyXN/QwenPaw-all-in-one-HFS-v2-candidate`. Do not push this GitHub repository root
directly to that Space: the root Dockerfile copies `hfs-dev.toml`, whose normal checkout
profile targets production. Export the reviewed candidate profile into an exact bundle
instead:

```bash
source_ref=$(git rev-parse HEAD)
bundle_dir=$(mktemp -d)
python3 scripts/export_hfs_space_bundle.py export \
  --source-commit "$source_ref" \
  --profile candidate \
  --output "$bundle_dir"
python3 scripts/export_hfs_space_bundle.py verify \
  --profile candidate \
  --bundle "$bundle_dir"
python3 scripts/export_hfs_space_bundle.py paths --profile candidate
```

The exporter accepts only the fixed `candidate` and `formal` enum profiles and requires a
clean checkout whose `HEAD` exactly matches the lowercase
40-character `source_ref`. Every source input is read from that commit. The exported
`hfs-dev.toml` comes from `hfs-dev.candidate.toml`; the Space-card Hugging Face links are
candidate-specific while GitHub source and release-asset URLs remain unchanged.
`BUILD_SOURCE.json` records wrapper/upstream provenance, and `SHA256SUMS` covers every other
allowlisted file exactly once. The verifier rejects missing, extra, non-regular, symlinked,
or production-target files.

The manual GitHub Actions workflow `.github/workflows/deploy-hf-space.yml` adds the remote
write gate. Dispatch it from GitHub `main` with:

```text
source_ref=<exact current GitHub main SHA>
confirm_upload=PUBLISH_CANDIDATE
```

The `hfs-candidate` GitHub environment must provide `HF_TOKEN`. Before uploading, the
workflow requires `source_ref == GITHUB_SHA == origin/main`, runs `static-check`, verifies
the bundle, confirms that the candidate Space already exists with `private=true`, and
refuses any remote path outside the bundle allowlist. It uploads without deletion, then
reads back the exact path set and checksums. It does not create a Space, change visibility,
sync Secrets/Variables, modify volumes, delete files, restart the Space, or run live smoke.

Sync candidate Settings separately from the ignored local ledger when that operation is
explicitly approved:

```bash
python3 scripts/hf_space_sync.py diff --manifest hfs-dev.candidate.toml --env-file .env
python3 scripts/hf_space_sync.py push --manifest hfs-dev.candidate.toml --env-file .env
python3 scripts/hf_space_sync.py diff --manifest hfs-dev.candidate.toml --env-file .env
```

An empty registered optional Secret is not pushed, does not count as missing, and is not
deleted by `--prune --yes`. A configured optional Secret is subject to the same placeholder,
seed-scan, push, and name-readback safeguards as `OPS_TOKEN`.

## Local Build

Local Docker build is optional for development. For this repository's normal maintenance workflow, heavy build/runtime verification can be performed by GitHub Actions and Hugging Face runtime instead.

```bash
bash scripts/local-build.sh
```

or:

```bash
docker build \
  -t qwenpaw-all-in-one-hfs:dev \
  --build-arg QWENPAW_SOURCE_REF=734c8b9fa610381fa6d79b10ae3641b6db4a8cb2 \
  --build-arg QWENPAW_SOURCE_VERSION=2.0.1 \
  --build-arg QWENPAW_CONSOLE_BUNDLE_URL=https://github.com/BlueSkyXN/QwenPaw-all-in-one-HFS/releases/download/qwenpaw-console-734c8b9f/qwenpaw-console-734c8b9fa610381fa6d79b10ae3641b6db4a8cb2.tar.gz \
  --build-arg QWENPAW_CONSOLE_BUNDLE_SHA256=c1bbaa54f7f07411b5948c2984c054c0e20352f46f6406101db65a9188aeb8cf \
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

Record the bucket ID only in local `.env` or another private deployment ledger:

```env
HF_STORAGE_BUCKET=<namespace>/<bucket-name>
```

## Production Hugging Face Space

This section describes the canonical production Space and its separately approved manual
release gate. It is not the candidate workflow above. A local semantic-manifest change does
not publish to a remote, update Space Settings, or cause Space takeover.

1. Confirm the fixed canonical Docker Space already exists with `private=true`.
2. Publish only the verified `formal` profile through the protected manual workflow.
3. Attach a private Storage Bucket read-write at `/data` if runtime data must survive
   restarts/rebuilds.
4. Set Variables/Secrets from `docs/configuration.md`.
5. Wait for build and runtime takeover.
6. Run smoke against the live Space URL.

GitHub push, HF Space repo SHA, runtime takeover and endpoint smoke are separate states. Execute them only as an explicitly approved release operation; treat the Space as available only after live smoke passes.

## Formal Production Workflow

`.github/workflows/deploy-hfs-formal.yml` is the reviewed canonical repository-write path.
It does not accept owner, repository, manifest, or Space inputs. Dispatch it from GitHub
`main` with:

```text
source_ref=<exact current GitHub main SHA>
confirm_upload=PUBLISH_FORMAL
```

The `hfs-production` GitHub environment must expose `HF_TOKEN`. The workflow requires
`source_ref == GITHUB_SHA == origin/main`, runs the static gate, and exports only
`--profile formal`. The profile fixes `hfs-dev.toml`, the wrapper source repository, and
the existing private `BlueSkyXN/QwenPaw-all-in-one-HFS` target. Before upload it rejects
remote paths outside the strict allowlist. After upload it downloads and verifies the exact
path set, compares `BUILD_SOURCE.json` and `SHA256SUMS`, binds readback provenance to the
authorized GitHub SHA, and only then requests `factory_reboot=True`.

The workflow does not create a Space, delete remote files, sync Settings, or change volumes.
Its successful factory-restart request is not proof that the rebuilt runtime reached
`RUNNING`, preserved existing accounts, or passed live smoke.

## Runtime Takeover

After the formal workflow uploads and requests a factory restart, the Space repository `sha`
can update before the running container does. Check runtime takeover explicitly:

```bash
hf spaces info BlueSkyXN/QwenPaw-all-in-one-HFS --json
```

The GitHub source SHA is carried by the downloaded `BUILD_SOURCE.wrapper_source_commit`; the
Hugging Face repository creates its own commit SHA. Deployment is not complete until:

```text
downloaded BUILD_SOURCE.wrapper_source_commit == authorized GitHub main SHA
repo sha == runtime.raw.sha
runtime.stage == RUNNING
live/authenticated smoke passed
```

`RUNNING_BUILDING` and `RUNNING_APP_STARTING` are transitional states. Keep polling until `RUNNING` and the runtime SHA has switched.

## Live Smoke

```bash
set -a
. ./.env
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
create the first admin account only with credentials stored in local `.env`:

```env
QWENPAW_ADMIN_USERNAME=<local-test-admin-name>
QWENPAW_ADMIN_PASSWORD=<local-test-admin-password>
```

Successful verification reaches `/chat` and shows `Logout`. Store screenshots under `local/`; they are local-only and ignored.

If the page already has an account, use the existing deployment credential record. Do not reset or overwrite persistent QwenPaw data unless that is an explicit maintenance task.
