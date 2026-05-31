# Release Checklist

## Static

```bash
bash scripts/static-check.sh
```

## Release Pins

Record:

```text
BASE_IMAGE_REF=node:22-slim@sha256:<digest>
QWENPAW_VERSION=1.1.9
QWENPAW_PACKAGE_SHA256=73ff2ca8b22dbfd6d233b678fb1de040bb41a1bff8b2b4091ecde866e1e57f63
UV_VERSION=0.7.20
QWENPAW_UPSTREAM_REF=2d9527bb097f9b09428190f80e1f3fd44f2ff453
```

## Build

```bash
docker build \
  --build-arg BASE_IMAGE_REF='node:22-slim@sha256:<digest>' \
  --build-arg QWENPAW_VERSION='1.1.9' \
  --build-arg QWENPAW_PACKAGE_SHA256='73ff2ca8b22dbfd6d233b678fb1de040bb41a1bff8b2b4091ecde866e1e57f63' \
  --build-arg UV_VERSION='0.7.20' \
  --build-arg QWENPAW_UPSTREAM_REF='2d9527bb097f9b09428190f80e1f3fd44f2ff453' \
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
- Run live smoke.
- Confirm `/_ops/version` reports expected release pins.
- Confirm admin is disabled unless intentionally enabled.
