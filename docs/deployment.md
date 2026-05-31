# Deployment

## Local Build

```bash
bash scripts/local-build.sh
```

or:

```bash
docker build \
  -t qwenpaw-all-in-one-hfs:dev \
  --build-arg QWENPAW_VERSION=1.1.9 \
  --build-arg QWENPAW_PACKAGE_SHA256=73ff2ca8b22dbfd6d233b678fb1de040bb41a1bff8b2b4091ecde866e1e57f63 \
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

## Hugging Face Space

1. Create a Docker Space.
2. Push this repository root to the Space repository.
3. Enable Persistent Storage if runtime data must survive restarts/rebuilds.
4. Set Variables/Secrets from `docs/configuration.md`.
5. Wait for build and runtime takeover.
6. Run smoke against the live Space URL.

GitHub push, HF Space repo SHA, runtime takeover and endpoint smoke are separate states. Treat the Space as available only after live smoke passes.
