# HFS Alignment

## Conclusion

`QwenPaw-all-in-one-HFS` belongs to:

```text
Pattern A: HFS Port Repository
HFS v2.1: project_class = "preview", target_role = "primary", sovereignty = "port", lane = "source", version_source = "commit"
Space root: repo root
Source of truth: Dockerfile's pinned upstream QwenPaw source commit
Maintained here: HFS runtime glue, Nginx, Supervisor, ops/admin, docs, smoke and CI
Semantic registry: hfs-dev.toml
```

This repository is not the upstream QwenPaw product source. It is the Hugging Face Docker Space delivery package for QwenPaw.

Routine Preview changes may update the canonical Space directly. The candidate profile is an
optional isolated target for high-risk validation, not a mandatory promotion step. Secret values
must originate in the manifest-declared Git-ignored plaintext ledger before they are copied to a
Space; canonical and candidate ledgers are intentionally separate.

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

## Source Lane and Build Evidence

This is the HFS `source` lane: Docker build fetches and installs a pinned upstream QwenPaw commit. It also downloads a checksum-pinned console bundle built from that exact commit, verifies it before extraction, and places it in the Python package source tree. The bundle avoids rebuilding the QwenPaw 2.0.1 local Monaco bundle inside the smaller Hugging Face build worker; it is a companion product of the source build, not an `artifact` lane application payload.

The semantic `hfs-dev.toml` does not duplicate pin values. Its project/Space identity, lane, version-source choice, and environment-key categories are consumed as HFS metadata. The following immutable build inputs remain implementation evidence in `Dockerfile`:

```text
BASE_IMAGE_REF                 image digest required for release
QWENPAW_SOURCE_REPO            upstream source repository
QWENPAW_SOURCE_REF             upstream source commit SHA
QWENPAW_SOURCE_VERSION         expected qwenpaw.__version__
QWENPAW_CONSOLE_BUNDLE_URL     console artifact for the same source SHA
QWENPAW_CONSOLE_BUNDLE_SHA256  console artifact checksum
UV_VERSION                     uv installer version
```

The default build pins upstream QwenPaw commit `734c8b9fa610381fa6d79b10ae3641b6db4a8cb2`, expects source version `2.0.1`, and consumes the console bundle whose URL contains the same full SHA and whose SHA-256 is `c1bbaa54f7f07411b5948c2984c054c0e20352f46f6406101db65a9188aeb8cf`. If the source commit changes, rebuild and repin the companion console bundle as well as the expected source version, then use `scripts/check-qwenpaw-pins.py` to verify the source and bundle together. `scripts/build-console-bundle.sh` and the manual `build-console-bundle` workflow are the paired build evidence; neither changes the lane.

## Shared Runtime Contract

Current implementation covers:

| Contract | Evidence |
| --- | --- |
| Space metadata | `README.md` frontmatter has `sdk: docker` and `app_port: 7860` |
| Space root | root-level `Dockerfile` |
| Semantic HFS registry | root-level `hfs-dev.toml` records identity, `port` sovereignty, `source` lane, `commit` version source, and environment-key ownership |
| Single public port | `README.md`, `Dockerfile EXPOSE`, and Nginx all use `7860` |
| Multi-service routing | Nginx routes QwenPaw, ops and admin under one public port |
| Reverse-proxy auth | persisted `trusted_proxies` includes only local Nginx; forwarding headers are sanitized |
| Readiness | `/readyz` follows upstream QwenPaw `/api/healthz`, not TCP alone |
| Runtime glue | `docker/` |
| Persistence | `/data/qwenpaw/*`, backed by a read-write Storage Bucket volume at `/data` and verified with pinned module-CLI runtime info plus `/_ops/persistence` |
| Ops | `/_ops` is read-only |
| Admin | `/_admin` is disabled by default and whitelisted when enabled |
| Static gate | `scripts/static-check.sh` and `scripts/validate-hfs-contract.sh` |
| Release bundle | `scripts/export_hfs_space_bundle.py` fixes the `candidate`/`formal` manifests, targets, provenance, checksums, and exact Space-root path set |
| Canonical deploy | `deploy-hfs-formal.yml` uses protected exact-main publication, full readback, and a post-readback factory restart request |
| Smoke | `scripts/hf-space-smoke.sh` |

## Source Fetch Boundary

Do not vendor upstream QwenPaw into this repository. Product behavior belongs upstream; this HFS port advances by changing `QWENPAW_SOURCE_REF`, validating `QWENPAW_SOURCE_VERSION`, publishing a checksum-pinned companion console bundle from the same commit when needed, and rebuilding the Space. Publishing remotely or waiting for Space takeover is a separate release gate after the local contract change; it is not implied by static alignment.
