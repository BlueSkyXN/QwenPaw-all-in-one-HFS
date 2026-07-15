#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ipaddress
import json
import os
import tempfile
from pathlib import Path
from typing import Any


LOCAL_NGINX_PROXY = ipaddress.ip_address("127.0.0.1")
LOCAL_NGINX_PROXY_ENTRY = "127.0.0.1/32"
FORBIDDEN_PROXY_ENTRIES = {"0.0.0.0/0", "::/0", "0.0.0.0", "::"}


class ConfigError(RuntimeError):
    pass


def _load_config(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(f"QwenPaw config does not exist: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigError(f"QwenPaw config is not valid JSON: {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ConfigError(f"QwenPaw config root must be a JSON object: {path}")
    return payload


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    mode = path.stat().st_mode & 0o777
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary_path, mode)
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def ensure_local_nginx_proxy(path: Path) -> bool:
    payload = _load_config(path)
    security = payload.get("security")
    if security is None:
        security = {}
        payload["security"] = security
    if not isinstance(security, dict):
        raise ConfigError("QwenPaw config security field must be a JSON object")

    proxies = security.get("trusted_proxies")
    if proxies is None:
        proxies = []
        security["trusted_proxies"] = proxies
    if not isinstance(proxies, list) or not all(isinstance(entry, str) for entry in proxies):
        raise ConfigError("QwenPaw security.trusted_proxies must be a string array")

    for entry in proxies:
        normalized_entry = entry.strip()
        if normalized_entry in FORBIDDEN_PROXY_ENTRIES:
            raise ConfigError(f"unsafe security.trusted_proxies entry: {entry!r}")
        try:
            network = ipaddress.ip_network(normalized_entry, strict=False)
        except ValueError as exc:
            raise ConfigError(f"invalid security.trusted_proxies entry: {entry!r}") from exc
        if LOCAL_NGINX_PROXY in network:
            return False

    proxies.append(LOCAL_NGINX_PROXY_ENTRY)
    _atomic_write_json(path, payload)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Ensure QwenPaw trusts the local HFS Nginx reverse proxy.",
    )
    parser.add_argument(
        "config_path",
        nargs="?",
        type=Path,
        default=(
            Path(os.environ.get("QWENPAW_WORKING_DIR", "/data/qwenpaw/working"))
            / "config.json"
        ),
    )
    args = parser.parse_args()

    changed = ensure_local_nginx_proxy(args.config_path)
    if changed:
        print("Updated QwenPaw trusted_proxies for the local HFS Nginx proxy", flush=True)
    else:
        print("QwenPaw trusted_proxies already covers the local HFS Nginx proxy", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
