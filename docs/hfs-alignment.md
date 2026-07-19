# HFS Alignment

## Conclusion

`QwenPaw-all-in-one-HFS` belongs to:

```text
Pattern A: HFS Port Repository
Runtime mode: source-fetch
Space root: repo root
Source of truth: pinned upstream QwenPaw source commit
Maintained here: HFS runtime glue, Nginx, Supervisor, ops/admin, docs, smoke and CI
Alignment manifest: hfs-dev.toml
```

This repository is not the upstream QwenPaw product source. It is the Hugging Face Docker Space delivery package for QwenPaw.

## Directory Ownership

Pattern A means the repository root is both:

```text
Hugging Face Space root
GitHub maintenance root
```

Do not add:

```text
cloud/hfs/README.md
cloud/hfs/Dockerfile
```

## Runtime Mode

The runtime mode is `source-fetch`: Docker build fetches a pinned upstream QwenPaw commit, builds the console frontend assets, copies them into the Python package source tree, and installs QwenPaw from that source.

Release pins:

```text
BASE_IMAGE_REF                 image digest required for release
QWENPAW_SOURCE_REPO            upstream source repository
QWENPAW_SOURCE_REF             upstream source commit SHA
QWENPAW_SOURCE_VERSION         expected qwenpaw.__version__
UV_VERSION                     uv installer version
```

The default build pins upstream QwenPaw commit `a15a69fca73e67c17dc47326e933eaa259fa0d8d` and expects source version `2.0.0.post3`. If the source commit changes, update the expected source version when needed and use the networked pin checker to verify whether the release must equal current upstream `main`.

## Shared Runtime Contract

Current implementation covers:

| Contract | Evidence |
| --- | --- |
| Space metadata | `README.md` frontmatter has `sdk: docker` and `app_port: 7860` |
| Space root | root-level `Dockerfile` |
| Manifest | root-level `hfs-dev.toml` |
| Single public port | `README.md`, `Dockerfile EXPOSE`, and Nginx all use `7860` |
| Multi-service routing | Nginx routes QwenPaw, ops and admin under one public port |
| Reverse-proxy auth | persisted `trusted_proxies` includes only local Nginx; forwarding headers are sanitized |
| Readiness | `/readyz` follows upstream QwenPaw `/api/healthz`, not TCP alone |
| Runtime glue | `docker/` |
| Persistence | `/data/qwenpaw/*`, backed by a read-write Storage Bucket volume at `/data` and verified with `hf spaces volumes list` plus `/_ops/persistence` |
| Ops | `/_ops` is read-only |
| Admin | `/_admin` is disabled by default and whitelisted when enabled |
| Static gate | `scripts/static-check.sh` and `scripts/validate-hfs-contract.sh` |
| Smoke | `scripts/hf-space-smoke.sh` |

## Source Fetch Boundary

Do not vendor upstream QwenPaw into this repository. Product behavior belongs upstream; this HFS port advances by changing `QWENPAW_SOURCE_REF`, validating `QWENPAW_SOURCE_VERSION`, and rebuilding the Space.
