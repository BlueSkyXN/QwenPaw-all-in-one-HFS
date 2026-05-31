# Agent Instructions — QwenPaw-all-in-one-HFS

This repository is a Hugging Face Docker Space port package for upstream QwenPaw.

## Classification

```text
Pattern A: HFS Port Repository
Runtime mode: artifact-at-build-time
Space root: repo root
```

Do not add `cloud/hfs/README.md` or `cloud/hfs/Dockerfile`.

## Boundaries

- Do not vendor upstream QwenPaw source unless the runtime mode is intentionally changed to `source-fetch`.
- Do not commit `.env`, API keys, channel tokens, local databases, logs or Hugging Face secrets.
- Keep runtime persistence under `/data/qwenpaw/*`.
- Keep pid files, sockets and transient runtime files under `/tmp/qwenpaw-run`.
- `/_ops` must remain read-only.
- `/_admin` must remain disabled by default and allow only whitelisted actions.

## Checks

Run before commit:

```bash
bash scripts/static-check.sh
bash scripts/validate-hfs-contract.sh
```

Runtime smoke requires a running container or Space:

```bash
OPS_TOKEN=dev-ops-token bash scripts/hf-space-smoke.sh http://127.0.0.1:7860
```
