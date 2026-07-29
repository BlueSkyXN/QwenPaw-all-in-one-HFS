# scripts navigation card

Maintainer automation for validation, local Docker build/run, and Space smoke checks. Read
this card before changing any script or moving validation logic.
Key files: `static-check.sh`, `validate-hfs-contract.sh`, `check-qwenpaw-pins.py`, `build-console-bundle.sh`,
`export_space_bundle.py`, `hf_space_sync.py`, `test_release_tools.py`,
`test_runtime_helpers.py`, `hf-space-smoke.sh`, `admin-smoke.sh`, `local-build.sh`, `local-run.sh`.

## Local invariants

- `static-check.sh` is the default no-Docker gate and must remain runnable with `bash`,
  `python3`, and Git only. Its standard-library tests create a temporary synthetic Git
  repository; they require no network, Hugging Face package, or credentials.
- `validate-hfs-contract.sh` is the repository-local HFS contract authority. It should fail
  on Pattern A drift, port drift, missing required files, release pin drift, routing drift,
  and ops/admin boundary regressions.
- `hf-space-smoke.sh` must check Nginx liveness, `/healthz`, `/readyz`, web root, protected
  `/_ops` endpoints when a token is present, and the default admin boundary.
- `admin-smoke.sh` must keep admin disabled-state checks by default and execute mutating
  admin actions only when explicitly requested.
- `check-qwenpaw-pins.py` is a networked release gate for package/version pin drift. Do
  not make it part of the default no-network static gate.
- `build-console-bundle.sh` must build only an immutable upstream commit, verify its source
  version, and emit a checksum beside the bundle. It must not publish artifacts itself.
- `export_space_bundle.py` must read its exact allowlist from a clean immutable commit,
  normalize only `hfs-dev.candidate.toml` to the exported `hfs-dev.toml`, reject production
  Space target leaks, and verify complete checksums. It must never perform remote actions.
- `hf_space_sync.py` requires all registered Variables and required Secrets. Registered
  optional Secrets may be empty; only non-empty values are pushed and required on readback,
  while prune retains registered optional remote names.
- Local build/run helpers may require Docker; syntax and static validation must not.

## Required before changes

- Keep command names aligned with root `AGENTS.md`, docs, and CI.
- For contract changes, cross-check `hfs-dev.toml`, `Dockerfile`, `README.md`,
  `docs/hfs-alignment.md`, and `.github/workflows/static-check.yml`.
- For smoke changes, cross-check `docker/nginx.conf`, `docker/ops_service.py`,
  `docker/admin_service.py`, and `docs/ops-runbook.md`.

## Do not

- Do not make `static-check.sh` require Docker, network, Hugging Face auth, or live Space
  access.
- Do not print real `OPS_TOKEN`, `ADMIN_TOKEN`, provider keys, or `.env.local` values.
- Do not let smoke pass if only `/nginx-health` works while app root or health/readiness
  endpoints are broken.
- Do not make scripts mutate remotes, deploy, or delete local data unless the user asked for
  that operation and the command name clearly signals it.
- Do not broaden the candidate bundle allowlist to include docs, CI, local material, value
  ledgers, the production manifest, or repository control files.

## Validation

Use root validation commands. For script-only edits:

```bash
bash scripts/static-check.sh
bash scripts/validate-hfs-contract.sh
git diff --check
```

Live smoke requires a running local container or deployed Space and may require `OPS_TOKEN`.

Targeted release-tool tests remain local and credential-free:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s scripts -p 'test_*.py'
```
