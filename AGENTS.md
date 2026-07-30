# Repository agent instructions

## Purpose

This repository is the Hugging Face Docker Space delivery package for upstream QwenPaw.
It is a Pattern A HFS Port Repository: the repository root is the Space root, and the
runtime fetches and installs the pinned upstream QwenPaw source tree during Docker build.

## Codex startup behavior

- Codex usually starts from the repository root, so this file is the main repo-local
  startup instruction.
- Local `AGENTS.md` files under subdirectories are navigation cards. They are not a
  replacement for this root router.
- Before editing a directory marked `Yes` in the Directory map, read that local card
  with `cat <path>/AGENTS.md`.
- If multiple nested `AGENTS.md` files exist on the path to a target file, read them
  from shallow to deep before making changes.
- If Codex is started from a subdirectory, the nearest local `AGENTS.md` may be loaded
  automatically. Still use this root file as the authoritative repository map.

## Repository classification

```text
Pattern: A - HFS Port Repository
Runtime mode: source-fetch
Space root: repo root
Public port: 7860
Internal app port: 8088
Ops service port: 8081
Admin service port: 8082
```

Do not move the Space implementation into `cloud/hfs/`. In this repository, root-level
`README.md`, `Dockerfile`, `hfs-dev.toml`, `docker/`, `scripts/`, and `docs/` are the
Space package surface.

## Directory map

| Path | Responsibility | Local AGENTS.md | Read when |
|---|---|---:|---|
| `AGENTS.md` | Startup router, directory map, command index, repository-wide boundaries | No | Update when repository structure, commands, or local cards change |
| `README.md` | Hugging Face Space card plus human maintainer overview | No | Updating Space metadata, public quick start, or documented runtime shape |
| `Dockerfile` | Root Docker Space build, upstream source fetch/install, release pin environment | No | Changing base image, source pins, OS packages, build args, ports, copied files, healthcheck, user, or entrypoint |
| `hfs-dev.toml` | Canonical Preview HFS semantic contract and required/optional Settings ownership | No | Changing HFS pattern, runtime mode, Settings categories, ports, or target Space |
| `hfs-dev.candidate.toml` | Optional high-risk Preview candidate profile; differs by Space, target role, and isolated env file | No | Changing candidate target or Settings ownership |
| `.dockerignore` | Docker build context boundary and secret/local exclusions | No | Changing what can enter the Space build context |
| `.gitignore` | Git working tree exclusions for local secrets, runtime data, caches, and ignored mirrors | No | Changing local/private file handling |
| `.env.example` | Non-secret example runtime values only | No | Adding or renaming public configuration keys |
| `.github/` | GitHub Actions for static validation, console build, and fixed-profile candidate/formal deploys | Yes | Any workflow, CI trigger, environment, Secret binding, or remote-write change |
| `docker/` | Runtime glue copied into the image: entrypoint, Nginx, Supervisor, healthcheck, ops/admin services, runtime env template | Yes | Any runtime behavior, routing, auth boundary, logs, persistence, process supervision, ops/admin, or healthcheck change |
| `scripts/` | Maintainer validation, local build/run, and smoke scripts | Yes | Any script, release gate, smoke behavior, Docker helper, or HFS contract validation change |
| `docs/` | Operator documentation: architecture, config, deployment, ops, release, security, HFS alignment | No | Documentation-only edits; keep facts aligned with root commands, `Dockerfile`, `hfs-dev.toml`, `docker/`, and `scripts/` |
| `local/` | Ignored local-only ledger, screenshots, browser checks, scratch clones, or private deployment records | No | Do not edit for repository changes; do not stage or publish |
| `.codex/` | Ignored local Codex app/session metadata | No | Do not edit for repository changes |

## On-demand cat protocol

Before editing files under a directory that has a local `AGENTS.md`, read that file
first:

```bash
cat docker/AGENTS.md
cat scripts/AGENTS.md
cat .github/AGENTS.md
```

Read only the card for the directory you are touching unless the change crosses
boundaries. Cross-boundary changes should read every affected card before editing.

## Command index

These commands are confirmed from repository scripts, docs, and CI. Do not invent
additional commands without checking real files first.

| Command | Purpose | Scope | Sandbox notes |
|---|---|---|---|
| `bash scripts/static-check.sh` | Default repository static gate. Runs HFS contract validation, optional external HFS alignment checker, Bash syntax checks, runtime/release-tool unit tests, and Python compile checks. | repo | No Docker or network required. Requires `bash`, `python3`, and Git. If the external `hfs-dev` checker is not present, the script prints an info message and still validates the local contract. |
| `bash scripts/validate-hfs-contract.sh` | Validate Pattern A repo shape, `hfs-dev.toml`, Space metadata, release pins, routing/security invariants, ignored secret patterns, and smoke coverage. | repo | No Docker or network required. Requires `python3` with `tomllib`, plus standard shell tools. |
| `python3 scripts/check-qwenpaw-pins.py` | Networked release check that fetches Dockerfile `QWENPAW_SOURCE_REF` from upstream QwenPaw and verifies the expected source version. Add `--require-upstream-main` for latest-main releases. | release pins | Requires network, `git`, and access to GitHub. Not part of the default static gate. |
| `bash scripts/build-console-bundle.sh <repo> <sha> <version> <output-dir>` | Build and checksum the console for an immutable upstream source commit. The manual `build-console-bundle` workflow uses this when the HFS builder cannot compile the frontend within its memory limit. | release artifact | Requires network, `git`, Node.js/npm, Python 3, and enough build memory. It creates local output only and does not publish. |
| `python3 scripts/export_hfs_space_bundle.py export --source-commit <sha> --profile <candidate\|formal> --output <empty-dir>` | Export an exact allowlisted candidate or formal Space bundle from a clean immutable checkout and generate provenance/checksums. Profile names fix the manifest and target Space; arbitrary owner/repo input is not accepted. | release bundle | Local-only and standard-library only. It performs no network or remote write. |
| `python3 scripts/export_hfs_space_bundle.py verify --profile <candidate\|formal> --bundle <dir>` | Verify the exact profile path set, fixed target, provenance, and complete SHA-256 coverage. | release bundle | Local-only and standard-library only. Safe for exported and downloaded bundles. |
| `python3 scripts/export_hfs_space_bundle.py paths --profile <candidate\|formal>` | Print the exact final bundle path allowlist used by CI remote preflight/readback. | release bundle | Read-only and credential-free. |
| `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s scripts -p 'test_*.py'` | Run runtime-helper plus fixed-profile exporter/Settings contract unit tests. | repo | Requires Git for a temporary synthetic repository; no Docker, network, Hugging Face package, or credentials required. |
| `git diff --check` | Whitespace/error check before publishing changes. | repo | Read-only Git check. |
| `bash -n docker/entrypoint.sh` | Targeted shell syntax check for runtime entrypoint edits. | `docker/` | Covered by `scripts/static-check.sh`; useful while iterating. |
| `bash -n docker/healthcheck.sh` | Targeted shell syntax check for container healthcheck edits. | `docker/` | Covered by `scripts/static-check.sh`; useful while iterating. |
| `bash -n scripts/admin-smoke.sh` | Targeted shell syntax check for admin smoke edits. | `scripts/` | Covered by `scripts/static-check.sh`; does not run network calls. |
| `bash -n scripts/hf-space-smoke.sh` | Targeted shell syntax check for smoke edits. | `scripts/` | Covered by `scripts/static-check.sh`; does not run network calls. |
| `bash -n scripts/local-build.sh` | Targeted shell syntax check for local Docker build helper edits. | `scripts/` | Covered by `scripts/static-check.sh`; does not build. |
| `bash -n scripts/local-run.sh` | Targeted shell syntax check for local Docker run helper edits. | `scripts/` | Covered by `scripts/static-check.sh`; does not run Docker. |
| `PYTHONDONTWRITEBYTECODE=1 python3 -m py_compile docker/prepare_runtime_config.py docker/ops_service.py docker/admin_service.py scripts/check-qwenpaw-pins.py scripts/test_runtime_helpers.py` | Targeted Python syntax check for runtime config, ops/admin, tests, and release pin checker edits. | `docker/`, `scripts/` | Covered by `scripts/static-check.sh`. Remove any generated `__pycache__` if run without `PYTHONDONTWRITEBYTECODE=1`. |
| `bash scripts/local-build.sh` | Build local Docker image `qwenpaw-all-in-one-hfs:dev` by default. | repo | Requires Docker daemon and network/package downloads during image build. Not a default sandbox check. |
| `OPS_TOKEN=dev-ops-token bash scripts/local-run.sh` | Run the local Docker container on port `7860`. | repo | Requires Docker daemon, local image, interactive container runtime, and port availability. |
| `OPS_TOKEN=dev-ops-token bash scripts/hf-space-smoke.sh http://127.0.0.1:7860` | Smoke a running local container. | repo/runtime | Requires a running container or service at the target URL. Protected `/_ops` checks run only when `OPS_TOKEN` or `QWENPAW_OPS_TOKEN` is set. |
| `ADMIN_EXPECTED_ENABLED=false bash scripts/admin-smoke.sh http://127.0.0.1:7860` | Smoke the default disabled admin boundary on a running local container. | repo/runtime | Requires a running container or service at the target URL. Mutating admin actions run only when explicitly enabled by env. |
| `bash scripts/hf-space-smoke.sh "$SMOKE_BASE_URL"` | Smoke a deployed Hugging Face Space. | live Space | Requires network, a reachable Space URL, and usually `OPS_TOKEN` from local/private environment. Do not paste real tokens into public logs or commits. |
| `python3 -m huggingface_hub.cli.hf spaces info BlueSkyXN/QwenPaw-all-in-one-HFS --expand sha,runtime,private` | Inspect Hugging Face repo/runtime state during release closeout with the pinned module CLI. | live Space | Requires network and configured Hugging Face authentication. Use only for requested release/deployment verification. |

## Global rules

- Treat `hfs-dev.toml` as the machine-readable contract. Keep it aligned with
  `README.md`, `Dockerfile`, `docker/nginx.conf`, `scripts/hf-space-smoke.sh`, and
  `docs/hfs-alignment.md`.
- Keep `hfs-dev.candidate.toml` aligned with the canonical Preview profile except for `space`,
  `target_role`, and `env_file`. The candidate
  exporter must normalize it to bundle-root `hfs-dev.toml`; never push the GitHub root
  directly to the candidate Space.
- `OPS_TOKEN` is required. Admin, provider, and channel Secrets remain registered optional
  values: empty local entries are not pushed or treated as missing and are retained by prune.
- Candidate deployment automation may write only the verified repository bundle to the fixed
  existing private candidate after exact-main and confirmation gates. Settings, visibility,
  volumes, lifecycle, runtime smoke, persistence, and cleanup are separate operations.
- Formal deployment automation may write only the verified `formal` bundle to the fixed
  existing private canonical Space after exact-main and `hfs-production` confirmation gates.
  It must complete path/checksum/provenance readback before requesting a factory restart;
  runtime takeover, live smoke, persistence, backup, and restore remain separate evidence.
- Keep this repository in Pattern A shape. Do not add `cloud/hfs/README.md` or
  `cloud/hfs/Dockerfile`.
- Do not vendor upstream QwenPaw source into this repository. The `source-fetch` runtime
  must fetch the pinned upstream commit during Docker build.
- If `QWENPAW_SOURCE_REF` changes, update `QWENPAW_SOURCE_VERSION` when needed, rebuild
  and repin `QWENPAW_CONSOLE_BUNDLE_URL`/`QWENPAW_CONSOLE_BUNDLE_SHA256`, and keep release
  pin docs and validators consistent.
- Release builds must use an immutable `BASE_IMAGE_REF` digest. Mutable base tags are
  acceptable only for local development builds.
- The public Space port is `7860`. QwenPaw runs internally on `8088`; ops-service runs
  on `8081`; admin-service runs on `8082`.
- Runtime persistence belongs under `/data/qwenpaw/*`; logs belong under
  `/data/var/logs`; pid files, sockets, and transient Nginx/Supervisor files belong
  under `/tmp/qwenpaw-run`.
- Build steps must not depend on `/data`; persistent storage exists only at runtime.
- `/_ops` must remain read-only. Public `/healthz` and `/readyz` route to ops health
  endpoints, but protected ops endpoints require `OPS_TOKEN`.
- `/_ops/config` may report secret presence booleans only. Never return secret values.
- `/_admin` must remain disabled by default. When enabled, mutating actions must remain
  whitelisted, token-protected, CSRF-protected, confirmation-gated, and audited.
- Keep Nginx as the single public-port front door. Do not expose internal service ports
  directly.
- Keep the container compatible with Hugging Face Docker Spaces and rootless runtime
  assumptions. Preserve user `1000` ownership for copied runtime files and writable
  directories unless there is a verified reason to change it.
- Prefer small, auditable Bash/Python stdlib changes over adding new dependencies.
- If adding a new long-term dependency, explain why existing OS packages, Python stdlib,
  Bash, or current image contents are insufficient.
- Documentation changes must be consistent with actual scripts/configs. Do not document
  commands or endpoints that are not present in the repository.
- Keep `local/`, `.env.local`, screenshots, database files, logs, exported secrets, and
  browser verification records local-only.

## Do not

- Do not commit `.env`, `.env.local`, `.env.*` other than `.env.example`, API keys,
  provider tokens, admin credentials, Hugging Face secrets, local databases, logs,
  screenshots, or runtime exports.
- Do not include real internal URLs, private deployment records, token values, browser
  session state, account names, prompts, memory contents, or customer/personal data in
  commits, docs, CI logs, PR text, or screenshots.
- Do not stage ignored `local/`, `.codex/`, `data/`, `logs/`, `*.secret`, `*.key`,
  `*.pem`, `*.sqlite`, `*.db`, or `*.log` files.
- Do not move the Space package into `cloud/hfs/`.
- Do not silently change the HFS pattern, runtime mode, ports, health endpoints, or
  persistence layout without updating `hfs-dev.toml`, docs, scripts, and validation.
- Do not make `/_ops` mutating or add request-supplied command execution to ops.
- Do not broaden `/_admin` into a shell, arbitrary command runner, package installer,
  file editor, or secret viewer.
- Do not enable `ADMIN_ENABLED=true` by default.
- Do not weaken token comparisons, remove security headers, or log token values.
- Do not replace the smoke script with checks that only test Nginx while skipping the app
  root and ops/admin boundaries.
- Do not treat `git push` or Space repo SHA update as proof that the running Space has
  taken over. Runtime `raw.sha`, runtime `stage`, and endpoint smoke are separate checks.
- Do not run deployment, push, merge, publish, or permission-changing commands unless the
  user explicitly asks for that operation.
- Do not add the unselected manifest, `.env*`, docs, workflows, `AGENTS.md`, `local/`, or
  scripts to either fixed-profile Space bundle allowlist.

## Validation

Default validation after any repository change:

1. `bash scripts/static-check.sh`
2. `bash scripts/validate-hfs-contract.sh`
3. `git diff --check`

For `docker/` runtime changes, also consider the targeted syntax checks while iterating:

```bash
bash -n docker/entrypoint.sh
bash -n docker/healthcheck.sh
bash -n scripts/admin-smoke.sh
PYTHONDONTWRITEBYTECODE=1 python3 -m py_compile docker/prepare_runtime_config.py docker/ops_service.py docker/admin_service.py
```

For `scripts/` changes, also consider:

```bash
bash -n scripts/hf-space-smoke.sh
bash -n scripts/admin-smoke.sh
bash -n scripts/local-build.sh
bash -n scripts/local-run.sh
```

For Docker/runtime behavior changes, run a local build/run/smoke when Docker and network
are available:

```bash
bash scripts/local-build.sh
OPS_TOKEN=dev-ops-token bash scripts/local-run.sh
OPS_TOKEN=dev-ops-token bash scripts/hf-space-smoke.sh http://127.0.0.1:7860
```

If Docker, network, credentials, or a running Space are unavailable, state exactly which
runtime checks were skipped and which static checks passed.

For release/deployment closeout requested by the user, validate all states separately:

```text
local HEAD == origin/main == downloaded BUILD_SOURCE.wrapper_source_commit
GitHub static-check succeeded for HEAD
formal path/checksum/provenance readback passed
Hugging Face repo sha == Hugging Face runtime.raw.sha
Hugging Face runtime.stage == RUNNING
live/authenticated smoke and existing-account persistence passed
worktree has no uncommitted tracked changes
```

## Notes for future agents

- This is not the upstream QwenPaw product source. Product-level behavior changes usually
  belong upstream, then this HFS port should advance `QWENPAW_SOURCE_REF`.
- The repository has no JavaScript package manager or Python packaging metadata for local
  app development. Commands come from shell scripts, Dockerfile, docs, and CI.
- `.github/workflows/static-check.yml` runs only `bash scripts/static-check.sh`; keep that
  script as the strongest no-Docker local gate.
- `scripts/static-check.sh` may use an external SKY-Prompt HFS alignment checker when it
  is mounted nearby. The repository-local contract must still be valid without that
  external checkout.
