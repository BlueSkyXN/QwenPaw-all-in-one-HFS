#!/usr/bin/env python3
"""Compatibility CLI for the historical candidate-only bundle command.

New automation should call ``export_hfs_space_bundle.py`` with an explicit
allowlisted profile. This wrapper fixes every operation to ``candidate`` and
retains the previous ``--manifest hfs-dev.candidate.toml`` spelling.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from export_hfs_space_bundle import (
    BUNDLE_PATHS,
    CANDIDATE_MANIFEST,
    REPO_ROOT,
    BundleError,
    export_bundle,
    verify_bundle,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    export_parser = subparsers.add_parser("export")
    export_parser.add_argument("--source-commit", required=True)
    export_parser.add_argument("--manifest", type=Path, required=True)
    export_parser.add_argument("--output", type=Path, required=True)

    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("--bundle", type=Path, required=True)
    subparsers.add_parser("paths")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "export":
            if args.manifest.as_posix() != CANDIDATE_MANIFEST:
                raise BundleError(f"--manifest must be exactly {CANDIDATE_MANIFEST}")
            export_bundle(REPO_ROOT, args.source_commit, "candidate", args.output)
            print(f"Exported verified candidate bundle for {args.source_commit}: {args.output}")
            return 0
        if args.command == "verify":
            verify_bundle(args.bundle, "candidate")
            print(f"Verified candidate bundle: {args.bundle}")
            return 0
        for path in BUNDLE_PATHS:
            print(path)
        return 0
    except (BundleError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
