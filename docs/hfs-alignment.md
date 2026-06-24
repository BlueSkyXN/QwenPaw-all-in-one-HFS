# HFS Alignment

## Conclusion

`QwenPaw-all-in-one-HFS` belongs to:

```text
Pattern A: HFS Port Repository
Runtime mode: artifact-at-build-time
Space root: repo root
Source of truth: QwenPaw PyPI release / upstream QwenPaw repository
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

The runtime mode is `artifact-at-build-time`: Docker build installs the selected `qwenpaw` package artifact.

Release pins:

```text
BASE_IMAGE_REF                 image digest required for release
QWENPAW_VERSION                package version
QWENPAW_PACKAGE_SHA256         package artifact SHA256
UV_VERSION                     uv installer version
QWENPAW_UPSTREAM_REF           metadata only
```

The default build pins `qwenpaw==1.1.12.post2` to wheel SHA256 `c07ba7780d0752281138298a6e2a7b0efd372bffab60e68d1d7e9856a5b16e6a` and upstream tag commit `09fc515c88a5e817870e6b975e66b5be81893e03`. If the package version changes, update both records.

## Shared Runtime Contract

Current implementation covers:

| Contract | Evidence |
| --- | --- |
| Space metadata | `README.md` frontmatter has `sdk: docker` and `app_port: 7860` |
| Space root | root-level `Dockerfile` |
| Manifest | root-level `hfs-dev.toml` |
| Single public port | `README.md`, `Dockerfile EXPOSE`, and Nginx all use `7860` |
| Multi-service routing | Nginx routes QwenPaw, ops and admin under one public port |
| Runtime glue | `docker/` |
| Persistence | `/data/qwenpaw/*` |
| Ops | `/_ops` is read-only |
| Admin | `/_admin` is disabled by default and whitelisted when enabled |
| Static gate | `scripts/static-check.sh` and `scripts/validate-hfs-contract.sh` |
| Smoke | `scripts/hf-space-smoke.sh` |

## Fallback Path

If the PyPI artifact lacks required static assets or runtime resources, change runtime mode to `source-fetch` and pin `QWENPAW_REF` to an upstream commit SHA. Do not silently keep `artifact-at-build-time` while building from source.
