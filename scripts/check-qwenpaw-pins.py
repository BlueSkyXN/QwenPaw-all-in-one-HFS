#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path
from typing import Any


DEFAULT_QWENPAW_REMOTE = "https://github.com/agentscope-ai/QwenPaw.git"
VERSION_FILE = "src/qwenpaw/__version__.py"
MAX_CONSOLE_BUNDLE_BYTES = 128 * 1024 * 1024


class CheckError(RuntimeError):
    pass


def run_text(args: list[str], *, cwd: Path | None = None, timeout: int = 60) -> str:
    proc = subprocess.run(
        args,
        cwd=cwd,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=timeout,
    )
    if proc.returncode != 0:
        raise CheckError(f"{' '.join(args)} failed: {proc.stderr.strip() or proc.stdout.strip()}")
    return proc.stdout


def dockerfile_args(path: Path) -> dict[str, str]:
    pattern = re.compile(r"^ARG\s+([A-Za-z_][A-Za-z0-9_]*)(?:=(.*))?$")
    args: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = pattern.match(line.strip())
        if match:
            args[match.group(1)] = (match.group(2) or "").strip()
    return args


def git_remote_ref(remote: str, ref: str) -> str:
    output = run_text(["git", "ls-remote", remote, ref])
    for line in output.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1] == ref:
            return parts[0]
    raise CheckError(f"Unable to resolve {ref} from {remote}")


def fetch_source_ref(remote: str, ref: str) -> tuple[str, str]:
    tmp = Path(tempfile.mkdtemp(prefix="qwenpaw-pin-check-"))
    try:
        run_text(["git", "init", "-q"], cwd=tmp)
        run_text(["git", "remote", "add", "origin", remote], cwd=tmp)
        if ref == "main":
            run_text(["git", "fetch", "--depth", "1", "origin", "main"], cwd=tmp, timeout=120)
            run_text(["git", "checkout", "--detach", "FETCH_HEAD"], cwd=tmp)
        else:
            if not re.fullmatch(r"[0-9a-f]{40}", ref):
                raise CheckError("QWENPAW_SOURCE_REF must be a 40-character lowercase commit SHA for release builds")
            run_text(["git", "fetch", "--depth", "1", "origin", ref], cwd=tmp, timeout=120)
            run_text(["git", "checkout", "--detach", ref], cwd=tmp)
        resolved = run_text(["git", "rev-parse", "HEAD"], cwd=tmp).strip()
        version_text = run_text(["git", "show", f"HEAD:{VERSION_FILE}"], cwd=tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    match = re.search(r"__version__\s*=\s*['\"]([^'\"]+)['\"]", version_text)
    if not match:
        raise CheckError(f"Unable to parse __version__ from {VERSION_FILE}")
    return resolved, match.group(1)


def fetch_console_bundle(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "qwenpaw-hfs-pin-check/1"})
    with urllib.request.urlopen(request, timeout=120) as response:  # noqa: S310 - release URL is validated by the caller.
        payload = response.read(MAX_CONSOLE_BUNDLE_BYTES + 1)
    if len(payload) > MAX_CONSOLE_BUNDLE_BYTES:
        raise CheckError("QWENPAW_CONSOLE_BUNDLE_URL exceeded the 128 MiB validation limit")
    return payload


def validate_console_bundle(payload: bytes) -> None:
    try:
        with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as archive:
            members = archive.getmembers()
    except tarfile.TarError as exc:
        raise CheckError(f"console bundle is not a valid gzip tar archive: {exc}") from exc

    if not members:
        raise CheckError("console bundle is empty")
    normalized_names: set[str] = set()
    for member in members:
        path = Path(member.name)
        if path.is_absolute() or ".." in path.parts:
            raise CheckError(f"console bundle contains unsafe path: {member.name}")
        if member.issym() or member.islnk():
            raise CheckError(f"console bundle contains link entry: {member.name}")
        normalized_names.add(member.name.removeprefix("./"))
    if "index.html" not in normalized_names:
        raise CheckError("console bundle does not contain index.html")


def check_equal(name: str, actual: str, expected: str, checks: list[dict[str, Any]]) -> None:
    checks.append({"name": name, "ok": actual == expected, "actual": actual, "expected": expected})


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check QwenPaw HFS Dockerfile source pins against the upstream Git repository.",
    )
    parser.add_argument("--repo-root", default=Path(__file__).resolve().parents[1], type=Path)
    parser.add_argument("--qwenpaw-remote", default=DEFAULT_QWENPAW_REMOTE)
    parser.add_argument(
        "--require-upstream-main",
        action="store_true",
        help="Fail when QWENPAW_SOURCE_REF is not the current upstream main commit.",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of human-readable output")
    args = parser.parse_args()

    root = args.repo_root.resolve()
    pins = dockerfile_args(root / "Dockerfile")
    checks: list[dict[str, Any]] = []
    notes: list[str] = []

    try:
        source_repo = pins.get("QWENPAW_SOURCE_REPO", "")
        source_ref = pins.get("QWENPAW_SOURCE_REF", "")
        source_version = pins.get("QWENPAW_SOURCE_VERSION", "")
        console_bundle_url = pins.get("QWENPAW_CONSOLE_BUNDLE_URL", "")
        console_bundle_sha256 = pins.get("QWENPAW_CONSOLE_BUNDLE_SHA256", "")

        check_equal("QWENPAW_SOURCE_REPO matches expected upstream", source_repo, args.qwenpaw_remote, checks)
        if not source_ref:
            raise CheckError("Dockerfile did not set QWENPAW_SOURCE_REF")
        if not source_version:
            raise CheckError("Dockerfile did not set QWENPAW_SOURCE_VERSION")
        if source_ref not in console_bundle_url:
            raise CheckError("QWENPAW_CONSOLE_BUNDLE_URL must identify QWENPAW_SOURCE_REF")
        if not re.fullmatch(r"[0-9a-f]{64}", console_bundle_sha256):
            raise CheckError("QWENPAW_CONSOLE_BUNDLE_SHA256 must be a 64-character lowercase SHA-256")

        resolved_ref, resolved_version = fetch_source_ref(source_repo or args.qwenpaw_remote, source_ref)
        check_equal("QWENPAW_SOURCE_REF resolves to pinned commit", resolved_ref, source_ref, checks)
        check_equal("QWENPAW_SOURCE_VERSION matches upstream source", resolved_version, source_version, checks)

        console_bundle = fetch_console_bundle(console_bundle_url)
        actual_console_sha256 = hashlib.sha256(console_bundle).hexdigest()
        check_equal(
            "QWENPAW_CONSOLE_BUNDLE_SHA256 matches downloaded artifact",
            actual_console_sha256,
            console_bundle_sha256,
            checks,
        )
        if actual_console_sha256 == console_bundle_sha256:
            validate_console_bundle(console_bundle)
            checks.append({"name": "QWENPAW_CONSOLE_BUNDLE archive is safe and complete", "ok": True})

        try:
            upstream_main = git_remote_ref(source_repo or args.qwenpaw_remote, "refs/heads/main")
            notes.append(f"upstream main: {upstream_main}")
            if args.require_upstream_main:
                check_equal(
                    "QWENPAW_SOURCE_REF matches current upstream main",
                    source_ref,
                    upstream_main,
                    checks,
                )
            elif upstream_main != source_ref:
                notes.append("pinned source ref intentionally differs from current upstream main")
        except CheckError as exc:
            if args.require_upstream_main:
                raise
            notes.append(f"upstream main check skipped: {exc}")
    except Exception as exc:  # noqa: BLE001 - compact CLI failure.
        checks.append({"name": "source pin check execution", "ok": False, "error": str(exc)})

    ok = all(check.get("ok") is True for check in checks)
    payload = {"ok": ok, "checks": checks, "notes": notes}

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"QwenPaw source pin check: {'PASS' if ok else 'FAIL'}")
        for check in checks:
            status = "PASS" if check.get("ok") is True else "FAIL"
            print(f"{status} {check.get('name')}")
            if check.get("ok") is not True:
                if "actual" in check or "expected" in check:
                    print(f"  actual:   {check.get('actual')}")
                    print(f"  expected: {check.get('expected')}")
                if "error" in check:
                    print(f"  error:    {check.get('error')}")
        for note in notes:
            print(f"NOTE {note}")

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
