#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


DEFAULT_QWENPAW_REMOTE = "https://github.com/agentscope-ai/QwenPaw.git"
PYPI_JSON_URL = "https://pypi.org/pypi/qwenpaw/json"


class CheckError(RuntimeError):
    pass


def run_text(args: list[str], *, timeout: int = 45) -> str:
    proc = subprocess.run(
        args,
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


def pypi_payload() -> dict[str, Any]:
    # Use curl instead of urllib so the check follows the system CA bundle on macOS.
    output = run_text(["curl", "-fsSL", "--max-time", "30", PYPI_JSON_URL], timeout=45)
    return json.loads(output)


def pypi_latest_version(payload: dict[str, Any]) -> str:
    version = payload.get("info", {}).get("version")
    if not isinstance(version, str) or not version:
        raise CheckError("PyPI payload did not expose info.version")
    return version


def pypi_wheel_sha256(payload: dict[str, Any], version: str) -> str:
    files = payload.get("releases", {}).get(version)
    if not isinstance(files, list) or not files:
        raise CheckError(f"PyPI payload did not expose files for qwenpaw=={version}")

    wheels = [
        file
        for file in files
        if isinstance(file, dict)
        and file.get("packagetype") == "bdist_wheel"
        and isinstance(file.get("filename"), str)
        and file["filename"].endswith("-py3-none-any.whl")
    ]
    if len(wheels) != 1:
        names = ", ".join(str(file.get("filename")) for file in wheels)
        raise CheckError(f"Expected one py3-none-any wheel for qwenpaw=={version}, got {len(wheels)}: {names}")

    digest = wheels[0].get("digests", {}).get("sha256")
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise CheckError(f"PyPI wheel for qwenpaw=={version} did not expose a sha256 digest")
    return digest


def git_remote_ref(remote: str, ref: str) -> str:
    output = run_text(["git", "ls-remote", remote, ref])
    for line in output.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1] == ref:
            return parts[0]
    raise CheckError(f"Unable to resolve {ref} from {remote}")


def git_remote_tag_commit(remote: str, tag: str) -> str:
    output = run_text(["git", "ls-remote", "--tags", remote, f"refs/tags/{tag}", f"refs/tags/{tag}^{{}}"])
    tag_ref = ""
    peeled_ref = ""
    for line in output.splitlines():
        parts = line.split()
        if len(parts) != 2:
            continue
        if parts[1] == f"refs/tags/{tag}^{{}}":
            peeled_ref = parts[0]
        elif parts[1] == f"refs/tags/{tag}":
            tag_ref = parts[0]
    commit = peeled_ref or tag_ref
    if not commit:
        raise CheckError(f"Unable to resolve tag {tag} from {remote}")
    return commit


def check_equal(name: str, actual: str, expected: str, checks: list[dict[str, Any]]) -> None:
    ok = actual == expected
    checks.append({"name": name, "ok": ok, "actual": actual, "expected": expected})


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check QwenPaw HFS Dockerfile pins against PyPI and the upstream tag.",
    )
    parser.add_argument("--repo-root", default=Path(__file__).resolve().parents[1], type=Path)
    parser.add_argument("--qwenpaw-remote", default=DEFAULT_QWENPAW_REMOTE)
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of human-readable output")
    args = parser.parse_args()

    root = args.repo_root.resolve()
    pins = dockerfile_args(root / "Dockerfile")
    checks: list[dict[str, Any]] = []
    notes: list[str] = []

    try:
        payload = pypi_payload()
        latest_version = pypi_latest_version(payload)
        pinned_version = pins.get("QWENPAW_VERSION", "")
        check_equal("QWENPAW_VERSION matches PyPI latest", pinned_version, latest_version, checks)

        if pinned_version:
            wheel_sha = pypi_wheel_sha256(payload, pinned_version)
            check_equal("QWENPAW_PACKAGE_SHA256 matches PyPI wheel", pins.get("QWENPAW_PACKAGE_SHA256", ""), wheel_sha, checks)

            tag = f"v{pinned_version}"
            tag_commit = git_remote_tag_commit(args.qwenpaw_remote, tag)
            check_equal("QWENPAW_UPSTREAM_REF matches upstream package tag", pins.get("QWENPAW_UPSTREAM_REF", ""), tag_commit, checks)

        try:
            upstream_main = git_remote_ref(args.qwenpaw_remote, "refs/heads/main")
            notes.append(f"upstream main: {upstream_main}")
        except CheckError as exc:
            notes.append(f"upstream main check skipped: {exc}")
    except Exception as exc:  # noqa: BLE001 - compact CLI failure.
        checks.append({"name": "pin check execution", "ok": False, "error": str(exc)})

    ok = all(check.get("ok") is True for check in checks)
    payload = {"ok": ok, "checks": checks, "notes": notes}

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"QwenPaw pin check: {'PASS' if ok else 'FAIL'}")
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
