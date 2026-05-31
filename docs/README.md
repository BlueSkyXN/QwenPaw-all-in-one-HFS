# QwenPaw HFS Documentation

This directory documents the deployable Hugging Face Docker Space package. It is written for maintainers who need to rebuild, operate, verify or hand off the Space without reading every script first.

## Current Shape

```text
Pattern: A - HFS Port Repository
Runtime mode: artifact-at-build-time
Space root: repository root
Public port: 7860
Primary runtime: QwenPaw behind Nginx and Supervisor
Persistence boundary: /data/qwenpaw/*
```

The upstream product source is not vendored here. This repository owns the HFS runtime glue, docs, smoke checks and release pins.

## Reading Order

1. [`hfs-alignment.md`](hfs-alignment.md) — classification and pin contract
2. [`architecture.md`](architecture.md) — process topology and routing
3. [`configuration.md`](configuration.md) — Variables and Secrets
4. [`deployment.md`](deployment.md) — local/Hugging Face deployment flow
5. [`ops-runbook.md`](ops-runbook.md) — health, logs and common failures
6. [`security.md`](security.md) — auth, secrets and admin boundary
7. [`release-checklist.md`](release-checklist.md) — release pin and smoke checklist

## Operator Shortcuts

Lightweight local checks:

```bash
bash scripts/static-check.sh
bash scripts/validate-hfs-contract.sh
```

Live Space smoke, using local-only values from `.env.local`:

```bash
set -a
. ./.env.local
set +a
bash scripts/hf-space-smoke.sh "$SMOKE_BASE_URL"
```

Closeout is not just a successful `git push`. Confirm `HEAD`, `origin/main`, `hf/main`, Hugging Face repo `sha`, Hugging Face `runtime.raw.sha`, and endpoint smoke all agree.

## What Belongs In Docs

- Public deployment shape, runtime boundaries, verification commands and release rules.
- Placeholder environment keys and non-secret examples.
- Operational runbooks that work from `/_ops` and logs.

## What Must Stay Local

- `.env.local` values, provider keys, admin credentials and Hugging Face secrets.
- Browser screenshots and login verification artifacts under `local/`.
- Runtime data, databases, logs and backups from `/data`.
