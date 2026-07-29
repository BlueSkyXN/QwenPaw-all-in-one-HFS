#!/usr/bin/env python3
"""Export and verify fixed-profile QwenPaw HFS bundles from an exact commit.

Only the reviewed ``candidate`` and ``formal`` profiles are accepted. Each
profile fixes its manifest, target Space, Space-card links, source repository,
and final path allowlist. The tool performs no remote operation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import tomllib

REPO_ROOT = Path(__file__).resolve().parents[1]
WRAPPER_REPOSITORY = "https://github.com/BlueSkyXN/QwenPaw-all-in-one-HFS"

FORMAL_MANIFEST = "hfs-dev.toml"
FORMAL_SPACE = "BlueSkyXN/QwenPaw-all-in-one-HFS"
FORMAL_SPACE_URL = f"https://huggingface.co/spaces/{FORMAL_SPACE}"
FORMAL_LIVE_URL = "https://blueskyxn-qwenpaw-all-in-one-hfs.hf.space"

CANDIDATE_MANIFEST = "hfs-dev.candidate.toml"
CANDIDATE_SPACE = "BlueSkyXN/QwenPaw-all-in-one-HFS-v2-candidate"
CANDIDATE_SPACE_URL = f"https://huggingface.co/spaces/{CANDIDATE_SPACE}"
CANDIDATE_LIVE_URL = "https://blueskyxn-qwenpaw-all-in-one-hfs-v2-candidate.hf.space"

PROFILE_NAMES = ("candidate", "formal")
PROFILES: dict[str, dict[str, str]] = {
    "candidate": {
        "manifest": CANDIDATE_MANIFEST,
        "space": CANDIDATE_SPACE,
        "space_url": CANDIDATE_SPACE_URL,
        "live_url": CANDIDATE_LIVE_URL,
    },
    "formal": {
        "manifest": FORMAL_MANIFEST,
        "space": FORMAL_SPACE,
        "space_url": FORMAL_SPACE_URL,
        "live_url": FORMAL_LIVE_URL,
    },
}

COMMON_SOURCE_TO_BUNDLE = {
    ".dockerignore": ".dockerignore",
    ".gitattributes": ".gitattributes",
    "Dockerfile": "Dockerfile",
    "LICENSE": "LICENSE",
    "README.md": "README.md",
    "docker/admin_service.py": "docker/admin_service.py",
    "docker/entrypoint.sh": "docker/entrypoint.sh",
    "docker/healthcheck.sh": "docker/healthcheck.sh",
    "docker/nginx.conf": "docker/nginx.conf",
    "docker/ops_service.py": "docker/ops_service.py",
    "docker/prepare_runtime_config.py": "docker/prepare_runtime_config.py",
    "docker/qwenpaw.env.runtime": "docker/qwenpaw.env.runtime",
    "docker/supervisord.conf": "docker/supervisord.conf",
}
GENERATED_PATHS = {"BUILD_SOURCE.json", "SHA256SUMS"}
BUNDLE_PATHS = tuple(
    sorted(set(COMMON_SOURCE_TO_BUNDLE.values()) | {"hfs-dev.toml"} | GENERATED_PATHS)
)

DOCKER_BUILD_ARGS = {
    "BASE_IMAGE_REF": "base_image_ref",
    "QWENPAW_SOURCE_REPO": "upstream_source_repository",
    "QWENPAW_SOURCE_REF": "upstream_source_ref",
    "QWENPAW_SOURCE_VERSION": "upstream_source_version",
    "QWENPAW_CONSOLE_BUNDLE_URL": "console_bundle_url",
    "QWENPAW_CONSOLE_BUNDLE_SHA256": "console_bundle_sha256",
}
BUILD_SOURCE_KEYS = {
    "schema_version",
    "source_kind",
    "wrapper_source_commit",
    "wrapper_source_repository",
    "target_space",
    "manifest_profile",
    "profile",
    "generated_at",
    *DOCKER_BUILD_ARGS.values(),
}
EXPECTED_MANIFEST_SCALARS = {
    "standard": "2.0",
    "project": "qwenpaw-all-in-one-hfs",
    "sovereignty": "port",
    "lane": "source",
    "version_source": "commit",
}

LOWER_SHA = re.compile(r"[0-9a-f]{40}")
SHA256 = re.compile(r"[0-9a-f]{64}")
DOCKER_ARG = re.compile(r"^ARG ([A-Z_][A-Z0-9_]*)=(.*)$")
CHECKSUM_LINE = re.compile(r"([0-9a-f]{64})  ([^\r\n]+)")
TOKEN_LITERAL = re.compile(
    r"(?:hf_[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{20,}|"
    r"github_pat_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9]{20,})"
)
FORMAL_TARGET_PATTERNS = (
    re.compile(rf"(?m)^\s*space\s*=\s*['\"]{re.escape(FORMAL_SPACE)}['\"]\s*(?:#.*)?$"),
    re.compile(rf"{re.escape(FORMAL_SPACE_URL)}(?![-A-Za-z0-9])"),
    re.compile(rf"{re.escape(FORMAL_LIVE_URL)}(?![-A-Za-z0-9])"),
    re.compile(rf"(?m)^\s*HF_SPACE_ID\s*=\s*{re.escape(FORMAL_SPACE)}\s*(?:#.*)?$"),
)


class BundleError(RuntimeError):
    """A release-bundle validation error safe to print in CI."""


def profile_config(profile_name: str) -> dict[str, str]:
    profile = PROFILES.get(profile_name)
    if profile is None:
        raise BundleError(f"--profile must be one of: {', '.join(PROFILE_NAMES)}")
    return profile


def source_to_bundle(profile_name: str) -> dict[str, str]:
    profile = profile_config(profile_name)
    mapping = dict(COMMON_SOURCE_TO_BUNDLE)
    mapping[profile["manifest"]] = "hfs-dev.toml"
    return mapping


def _git(repo: Path, *args: str, text: bool = True) -> str | bytes:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=text,
        check=False,
    )
    if result.returncode != 0:
        raise BundleError(f"Git command failed: git {' '.join(args)}")
    return result.stdout


def _require_source_commit(repo: Path, source_commit: str) -> None:
    if not LOWER_SHA.fullmatch(source_commit):
        raise BundleError("--source-commit must be a 40-character lowercase Git SHA")
    head = str(_git(repo, "rev-parse", "HEAD")).strip()
    if head != source_commit:
        raise BundleError("source commit must equal the current checkout HEAD")
    _git(repo, "cat-file", "-e", f"{source_commit}^{{commit}}")
    dirty = str(_git(repo, "status", "--porcelain=v1", "--untracked-files=all"))
    if dirty:
        raise BundleError("refusing to export a dirty checkout")


def _tree_mode(repo: Path, source_commit: str, source_path: str) -> int:
    output = str(_git(repo, "ls-tree", source_commit, "--", source_path)).strip()
    match = re.fullmatch(r"(100644|100755) blob [0-9a-f]{40}\t(.+)", output)
    if not match or match.group(2) != source_path:
        raise BundleError(f"required tracked bundle input is missing or unsafe: {source_path}")
    return 0o755 if match.group(1) == "100755" else 0o644


def _blob(repo: Path, source_commit: str, source_path: str) -> bytes:
    output = _git(repo, "show", f"{source_commit}:{source_path}", text=False)
    return cast(bytes, output)


def _docker_args(dockerfile: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in dockerfile.splitlines():
        match = DOCKER_ARG.fullmatch(line)
        if match and match.group(1) in DOCKER_BUILD_ARGS:
            values[match.group(1)] = match.group(2)
    missing = sorted(set(DOCKER_BUILD_ARGS) - set(values))
    if missing:
        raise BundleError(f"Dockerfile is missing required release build args: {missing}")
    if not LOWER_SHA.fullmatch(values["QWENPAW_SOURCE_REF"]):
        raise BundleError("Dockerfile QWENPAW_SOURCE_REF must be an immutable commit")
    if not SHA256.fullmatch(values["QWENPAW_CONSOLE_BUNDLE_SHA256"]):
        raise BundleError("Dockerfile console bundle checksum must be SHA-256")
    if values["QWENPAW_SOURCE_REF"] not in values["QWENPAW_CONSOLE_BUNDLE_URL"]:
        raise BundleError("Dockerfile console bundle URL must contain the upstream source ref")
    return values


def _decode_readme(raw: bytes) -> str:
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise BundleError("README.md must be UTF-8") from exc


def _readme_for_profile(raw: bytes, profile_name: str) -> bytes:
    text = _decode_readme(raw)
    if profile_name == "candidate":
        text = re.sub(
            rf"{re.escape(FORMAL_SPACE_URL)}(?![-A-Za-z0-9])",
            CANDIDATE_SPACE_URL,
            text,
        )
        text = text.replace(FORMAL_LIVE_URL, CANDIDATE_LIVE_URL)
        text = re.sub(
            rf"(?m)^(\s*HF_SPACE_ID\s*=\s*){re.escape(FORMAL_SPACE)}(\s*(?:#.*)?)$",
            rf"\g<1>{CANDIDATE_SPACE}\g<2>",
            text,
        )
    if WRAPPER_REPOSITORY not in text:
        raise BundleError("README must preserve the fixed GitHub wrapper source URL")
    return text.encode("utf-8")


def _validate_manifest(raw: bytes, profile_name: str) -> None:
    profile = profile_config(profile_name)
    try:
        manifest = tomllib.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise BundleError("selected manifest is not valid UTF-8 TOML") from exc
    expected = {**EXPECTED_MANIFEST_SCALARS, "space": profile["space"]}
    for key, value in expected.items():
        if manifest.get(key) != value:
            raise BundleError(f"selected manifest has an unexpected {key}")


def _build_source(source_commit: str, dockerfile: str, profile_name: str) -> dict[str, Any]:
    profile = profile_config(profile_name)
    args = _docker_args(dockerfile)
    evidence: dict[str, Any] = {
        "schema_version": 1,
        "source_kind": "git-commit",
        "wrapper_source_commit": source_commit,
        "wrapper_source_repository": WRAPPER_REPOSITORY,
        "target_space": profile["space"],
        "manifest_profile": profile["manifest"],
        "profile": profile_name,
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    evidence.update({field: args[arg] for arg, field in DOCKER_BUILD_ARGS.items()})
    return evidence


def _write_file(path: Path, payload: bytes, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    path.chmod(mode)


def _write_checksums(bundle: Path) -> None:
    lines = []
    for relative in BUNDLE_PATHS:
        if relative == "SHA256SUMS":
            continue
        digest = hashlib.sha256((bundle / relative).read_bytes()).hexdigest()
        lines.append(f"{digest}  {relative}\n")
    _write_file(bundle / "SHA256SUMS", "".join(lines).encode("utf-8"))


def export_bundle(
    repo: Path,
    source_commit: str,
    profile_name: str,
    output: Path,
) -> None:
    profile_config(profile_name)
    repo = repo.resolve()
    _require_source_commit(repo, source_commit)

    output = output.expanduser()
    if output.is_symlink():
        raise BundleError("--output must not be a symlink")
    if output.exists():
        if not output.is_dir() or any(output.iterdir()):
            raise BundleError("--output must be a new or empty directory")
    else:
        output.mkdir(parents=True)

    mapping = source_to_bundle(profile_name)
    sources: dict[str, tuple[bytes, int]] = {}
    for source_path in mapping:
        sources[source_path] = (
            _blob(repo, source_commit, source_path),
            _tree_mode(repo, source_commit, source_path),
        )

    manifest_path = profile_config(profile_name)["manifest"]
    _validate_manifest(sources[manifest_path][0], profile_name)
    dockerfile = sources["Dockerfile"][0].decode("utf-8")
    evidence = _build_source(source_commit, dockerfile, profile_name)

    for source_path, bundle_path in mapping.items():
        payload, mode = sources[source_path]
        if source_path == "README.md":
            payload = _readme_for_profile(payload, profile_name)
        _write_file(output / bundle_path, payload, mode)

    _write_file(
        output / "BUILD_SOURCE.json",
        (json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8"),
    )
    _write_checksums(output)
    verify_bundle(output, profile_name)


def _bundle_inventory(bundle: Path) -> tuple[set[str], set[str]]:
    files: set[str] = set()
    directories: set[str] = set()
    for current, dirnames, filenames in os.walk(bundle, followlinks=False):
        current_path = Path(current)
        for name in dirnames:
            path = current_path / name
            relative = path.relative_to(bundle).as_posix()
            if path.is_symlink() or not stat.S_ISDIR(path.lstat().st_mode):
                raise BundleError(f"bundle contains a non-directory or symlink node: {relative}")
            directories.add(relative)
        for name in filenames:
            path = current_path / name
            relative = path.relative_to(bundle).as_posix()
            if path.is_symlink() or not stat.S_ISREG(path.lstat().st_mode):
                raise BundleError(f"bundle contains a non-regular or symlink file: {relative}")
            files.add(relative)
    return files, directories


def _verify_checksums(bundle: Path, files: set[str]) -> None:
    checksums: dict[str, str] = {}
    try:
        lines = (bundle / "SHA256SUMS").read_text(encoding="utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise BundleError("SHA256SUMS must be UTF-8") from exc
    for line in lines:
        match = CHECKSUM_LINE.fullmatch(line)
        if not match:
            raise BundleError("SHA256SUMS contains a malformed entry")
        relative = match.group(2)
        if relative in checksums:
            raise BundleError(f"SHA256SUMS contains a duplicate entry: {relative}")
        checksums[relative] = match.group(1)

    expected = files - {"SHA256SUMS"}
    if set(checksums) != expected:
        raise BundleError("SHA256SUMS must cover every other bundle file exactly once")
    for relative in sorted(expected):
        digest = hashlib.sha256((bundle / relative).read_bytes()).hexdigest()
        if checksums[relative] != digest:
            raise BundleError(f"checksum mismatch: {relative}")


def _load_build_source(bundle: Path, profile_name: str) -> dict[str, Any]:
    profile = profile_config(profile_name)
    try:
        evidence = json.loads((bundle / "BUILD_SOURCE.json").read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BundleError("BUILD_SOURCE.json is not valid UTF-8 JSON") from exc
    if not isinstance(evidence, dict) or set(evidence) != BUILD_SOURCE_KEYS:
        raise BundleError("BUILD_SOURCE.json has an unexpected schema")
    if evidence.get("schema_version") != 1 or evidence.get("source_kind") != "git-commit":
        raise BundleError("BUILD_SOURCE.json must identify schema 1 and a Git commit")
    if not LOWER_SHA.fullmatch(str(evidence.get("wrapper_source_commit", ""))):
        raise BundleError("BUILD_SOURCE.json lacks an immutable wrapper source commit")
    if evidence.get("wrapper_source_repository") != WRAPPER_REPOSITORY:
        raise BundleError("BUILD_SOURCE.json names an unexpected wrapper repository")
    if evidence.get("target_space") != profile["space"]:
        raise BundleError("BUILD_SOURCE.json names an unexpected Space target")
    if evidence.get("manifest_profile") != profile["manifest"]:
        raise BundleError("BUILD_SOURCE.json names an unexpected manifest profile")
    if evidence.get("profile") != profile_name:
        raise BundleError("BUILD_SOURCE.json names an unexpected release profile")
    try:
        datetime.strptime(str(evidence.get("generated_at")), "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=UTC
        )
    except ValueError as exc:
        raise BundleError("BUILD_SOURCE.json generated_at must be UTC RFC 3339") from exc
    return evidence


def _verify_text_guards(bundle: Path, files: set[str], profile_name: str) -> None:
    for relative in sorted(files - {"SHA256SUMS"}):
        try:
            text = (bundle / relative).read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise BundleError(f"bundle text file is not UTF-8: {relative}") from exc
        if profile_name == "candidate":
            for pattern in FORMAL_TARGET_PATTERNS:
                if pattern.search(text):
                    raise BundleError(f"candidate bundle leaks the formal Space target: {relative}")
        if TOKEN_LITERAL.search(text):
            raise BundleError(f"bundle contains a token-like literal: {relative}")


def _verify_readme(readme: str, profile_name: str) -> None:
    profile = profile_config(profile_name)
    if profile["space_url"] not in readme or profile["live_url"] not in readme:
        raise BundleError(f"{profile_name} README does not identify the fixed Space and live URL")
    if f"HF_SPACE_ID={profile['space']}" not in readme:
        raise BundleError(f"{profile_name} README does not identify the fixed HF_SPACE_ID")
    if WRAPPER_REPOSITORY not in readme:
        raise BundleError("README does not preserve the fixed GitHub wrapper source URL")


def verify_bundle(bundle: Path, profile_name: str) -> None:
    profile_config(profile_name)
    if bundle.is_symlink() or not bundle.is_dir():
        raise BundleError("--bundle must be an existing non-symlink directory")
    bundle = bundle.resolve()
    files, directories = _bundle_inventory(bundle)
    expected_files = set(BUNDLE_PATHS)
    expected_directories = {
        str(parent)
        for relative in BUNDLE_PATHS
        for parent in Path(relative).parents
        if str(parent) != "."
    }
    if files != expected_files:
        missing = sorted(expected_files - files)
        extra = sorted(files - expected_files)
        raise BundleError(f"bundle path set mismatch; missing={missing}; extra={extra}")
    if directories != expected_directories:
        raise BundleError("bundle contains an unexpected or missing directory")

    _verify_checksums(bundle, files)
    _validate_manifest((bundle / "hfs-dev.toml").read_bytes(), profile_name)
    if (bundle / ".gitattributes").read_text(encoding="utf-8") != "* text=auto eol=lf\n":
        raise BundleError("bundle .gitattributes must enforce the minimal LF text contract")

    evidence = _load_build_source(bundle, profile_name)
    dockerfile = (bundle / "Dockerfile").read_text(encoding="utf-8")
    docker_args = _docker_args(dockerfile)
    for argument, field in DOCKER_BUILD_ARGS.items():
        if evidence.get(field) != docker_args[argument]:
            raise BundleError(f"BUILD_SOURCE.json disagrees with Dockerfile at {field}")
    if re.search(r"(?mi)^\s*(?:COPY|ADD)(?:\s+--\S+)*\s+\.\s+", dockerfile):
        raise BundleError("Dockerfile must not use COPY . or ADD .")

    readme = (bundle / "README.md").read_text(encoding="utf-8")
    _verify_readme(readme, profile_name)
    _verify_text_guards(bundle, files, profile_name)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    export_parser = subparsers.add_parser("export", help="export an exact-commit HFS bundle")
    export_parser.add_argument("--source-commit", required=True)
    export_parser.add_argument("--profile", required=True, choices=PROFILE_NAMES)
    export_parser.add_argument("--output", type=Path, required=True)

    verify_parser = subparsers.add_parser("verify", help="verify an HFS bundle")
    verify_parser.add_argument("--profile", required=True, choices=PROFILE_NAMES)
    verify_parser.add_argument("--bundle", type=Path, required=True)

    paths_parser = subparsers.add_parser("paths", help="print the final bundle path allowlist")
    paths_parser.add_argument("--profile", required=True, choices=PROFILE_NAMES)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "export":
            export_bundle(REPO_ROOT, args.source_commit, args.profile, args.output)
            print(f"Exported verified {args.profile} bundle for {args.source_commit}: {args.output}")
            return 0
        if args.command == "verify":
            verify_bundle(args.bundle, args.profile)
            print(f"Verified {args.profile} bundle: {args.bundle}")
            return 0
        profile_config(args.profile)
        for path in BUNDLE_PATHS:
            print(path)
        return 0
    except (BundleError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
