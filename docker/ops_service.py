#!/usr/bin/env python3
from __future__ import annotations

import hmac
import hashlib
import json
import os
import platform
import shutil
import socket
import subprocess
import time
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

PORT = int(os.environ.get("QWENPAW_OPS_PORT", "8081"))
STARTED_AT = time.time()
LOG_DIR = Path(os.environ.get("QWENPAW_OPS_LOG_DIR", "/data/var/logs"))
SUPERVISOR_CONF = os.environ.get("SUPERVISOR_CONF", "/home/user/app/docker/supervisord.conf")
OPS_SESSION_COOKIE = "qwenpaw_ops_session"

LOG_WHITELIST = {
    "qwenpaw": "qwenpaw.log",
    "qwenpaw-err": "qwenpaw.err.log",
    "nginx": "nginx.log",
    "nginx-err": "nginx.err.log",
    "nginx-access": "nginx-access.log",
    "nginx-error": "nginx-error.log",
    "ops-service": "ops-service.log",
    "ops-service-err": "ops-service.err.log",
    "admin-service": "admin-service.log",
    "admin-service-err": "admin-service.err.log",
    "xvfb": "xvfb.log",
    "xvfb-err": "xvfb.err.log",
    "supervisord": "supervisord.log",
}

SECRET_KEYS = [
    "OPS_TOKEN",
    "ADMIN_TOKEN",
    "ADMIN_CSRF_TOKEN",
    "DASHSCOPE_API_KEY",
    "OPENAI_API_KEY",
    "GEMINI_API_KEY",
    "TELEGRAM_BOT_TOKEN",
    "DISCORD_BOT_TOKEN",
    "QWENPAW_AUTH_ENABLED",
]


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def parse_int(value: Any, default: int, minimum: int | None = None, maximum: int | None = None) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    if minimum is not None:
        parsed = max(parsed, minimum)
    if maximum is not None:
        parsed = min(parsed, maximum)
    return parsed


def parse_bool(value: str, default: bool = False) -> bool:
    if not value:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def json_response(handler: BaseHTTPRequestHandler, status: int, body: dict[str, Any]) -> None:
    payload = json.dumps(body, ensure_ascii=False, sort_keys=True).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Cache-Control", "no-store")
    add_security_headers(handler)
    maybe_set_session_cookie(handler)
    handler.send_header("Content-Length", str(len(payload)))
    handler.end_headers()
    handler.wfile.write(payload)


def text_response(handler: BaseHTTPRequestHandler, status: int, body: str, content_type: str = "text/plain; charset=utf-8") -> None:
    payload = body.encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Cache-Control", "no-store")
    add_security_headers(handler)
    maybe_set_session_cookie(handler)
    handler.send_header("Content-Length", str(len(payload)))
    handler.end_headers()
    handler.wfile.write(payload)


def add_security_headers(handler: BaseHTTPRequestHandler) -> None:
    handler.send_header("X-Content-Type-Options", "nosniff")
    handler.send_header("Referrer-Policy", "no-referrer")
    handler.send_header("X-Frame-Options", "DENY")
    handler.send_header("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")


def session_ttl_seconds() -> int:
    return parse_int(env("OPS_SESSION_TTL_SECONDS"), 3600, minimum=60, maximum=86400)


def sign_message(*parts: str) -> str:
    payload = "|".join(parts).encode("utf-8")
    return hmac.new(env("OPS_TOKEN").encode("utf-8"), payload, hashlib.sha256).hexdigest()


def make_session() -> tuple[str, int]:
    expires_at = int(time.time()) + session_ttl_seconds()
    nonce = hashlib.sha256(f"{time.time()}:{os.urandom(16).hex()}".encode("utf-8")).hexdigest()[:32]
    signature = sign_message("ops-session", str(expires_at), nonce)
    return f"{expires_at}.{nonce}.{signature}", expires_at


def parse_session(cookie_value: str) -> bool:
    try:
        expires_raw, nonce, signature = cookie_value.split(".", 2)
        expires_at = int(expires_raw)
    except (AttributeError, ValueError):
        return False
    if expires_at < int(time.time()) or not nonce or not signature or not env("OPS_TOKEN"):
        return False
    expected = sign_message("ops-session", str(expires_at), nonce)
    return hmac.compare_digest(signature, expected)


def cookie_secure_enabled(handler: BaseHTTPRequestHandler) -> bool:
    mode = env("OPS_COOKIE_SECURE", "auto").strip().lower()
    if mode in {"1", "true", "yes", "on"}:
        return True
    if mode in {"0", "false", "no", "off"}:
        return False
    proto = handler.headers.get("X-Forwarded-Proto", "").split(",", 1)[0].strip().lower()
    return proto == "https"


def maybe_set_session_cookie(handler: BaseHTTPRequestHandler) -> None:
    if getattr(handler, "ops_auth_source", "") not in {"header", "query"}:
        return
    value, expires_at = make_session()
    max_age = max(expires_at - int(time.time()), 0)
    secure = "; Secure" if cookie_secure_enabled(handler) else ""
    handler.send_header(
        "Set-Cookie",
        f"{OPS_SESSION_COOKIE}={value}; Path=/_ops/; Max-Age={max_age}; HttpOnly; SameSite=Lax{secure}",
    )


def cookie_authenticated(handler: BaseHTTPRequestHandler) -> bool:
    raw = handler.headers.get("Cookie", "")
    if not raw:
        return False
    cookie = SimpleCookie()
    try:
        cookie.load(raw)
    except Exception:
        return False
    morsel = cookie.get(OPS_SESSION_COOKIE)
    return bool(morsel and parse_session(morsel.value))


def auth_source(handler: BaseHTTPRequestHandler) -> str:
    expected = env("OPS_TOKEN")
    if not expected:
        return ""
    token = handler.headers.get("X-Ops-Token", "")
    auth = handler.headers.get("Authorization", "")
    if not token and auth.startswith("Bearer "):
        token = auth.removeprefix("Bearer ").strip()
    if token and hmac.compare_digest(token, expected):
        return "header"
    query = parse_qs(urlparse(handler.path).query)
    token = (query.get("token") or [""])[0]
    if token and hmac.compare_digest(token, expected):
        return "query"
    if cookie_authenticated(handler):
        return "cookie"
    return ""


def require_auth(handler: BaseHTTPRequestHandler) -> bool:
    if not env("OPS_TOKEN"):
        json_response(handler, 503, {"ok": False, "error": "OPS_TOKEN is not configured", "locked": True})
        return False
    handler.ops_auth_source = auth_source(handler)
    if not handler.ops_auth_source:
        json_response(handler, 401, {"ok": False, "error": "unauthorized"})
        return False
    return True


def query_token_redirect(handler: BaseHTTPRequestHandler) -> None:
    handler.send_response(303)
    handler.send_header("Location", "/_ops/")
    handler.send_header("Cache-Control", "no-store")
    add_security_headers(handler)
    maybe_set_session_cookie(handler)
    handler.send_header("Content-Length", "0")
    handler.end_headers()


def tcp_check(host: str, port: int, timeout: float = 1.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def fixed_supervisor_status() -> list[dict[str, str]]:
    try:
        proc = subprocess.run(
            ["supervisorctl", "-c", SUPERVISOR_CONF, "status"],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=5,
        )
    except Exception as exc:
        return [{"name": "supervisor", "state": "ERROR", "detail": str(exc)}]
    lines = (proc.stdout or proc.stderr or "").splitlines()
    result: list[dict[str, str]] = []
    for line in lines:
        parts = line.split(None, 2)
        if len(parts) >= 2:
            result.append({"name": parts[0], "state": parts[1], "detail": parts[2] if len(parts) > 2 else ""})
    if not result and proc.returncode != 0:
        result.append({"name": "supervisor", "state": "ERROR", "detail": proc.stderr.strip()})
    return result


def safe_config() -> dict[str, Any]:
    return {
        "ports": {
            "public": int(os.environ.get("PORT", "7860")),
            "qwenpaw": int(os.environ.get("QWENPAW_PORT", "8088")),
            "ops": PORT,
            "admin": int(os.environ.get("QWENPAW_ADMIN_PORT", "8082")),
        },
        "paths": {
            "working": os.environ.get("QWENPAW_WORKING_DIR", "/data/qwenpaw/working"),
            "secrets": os.environ.get("QWENPAW_SECRET_DIR", "/data/qwenpaw/secrets"),
            "backups": os.environ.get("QWENPAW_BACKUP_DIR", "/data/qwenpaw/backups"),
            "logs": str(LOG_DIR),
        },
        "flags": {
            "admin_enabled": os.environ.get("ADMIN_ENABLED", "false"),
            "disabled_channels": os.environ.get("QWENPAW_DISABLED_CHANNELS", ""),
            "running_in_container": os.environ.get("QWENPAW_RUNNING_IN_CONTAINER", ""),
        },
        "ops": {
            "session_ttl_seconds": session_ttl_seconds(),
            "cookie_secure": env("OPS_COOKIE_SECURE", "auto"),
        },
        "secret_presence": {key: bool(os.environ.get(key)) for key in SECRET_KEYS},
    }


def version_info() -> dict[str, Any]:
    return {
        "service": "qwenpaw-all-in-one-hfs",
        "python": platform.python_version(),
        "platform": platform.platform(),
        "uptime_seconds": round(time.time() - STARTED_AT, 3),
        "release_pins": {
            "BASE_IMAGE_REF": os.environ.get("QWENPAW_AIO_BUILD_BASE_IMAGE_REF", os.environ.get("QWENPAW_HFS_BUILD_BASE_IMAGE_REF", "")),
            "QWENPAW_VERSION": os.environ.get("QWENPAW_AIO_BUILD_QWENPAW_VERSION", os.environ.get("QWENPAW_HFS_BUILD_QWENPAW_VERSION", "")),
            "QWENPAW_PACKAGE_SHA256_present": bool(os.environ.get("QWENPAW_AIO_BUILD_QWENPAW_PACKAGE_SHA256", os.environ.get("QWENPAW_HFS_BUILD_QWENPAW_PACKAGE_SHA256", ""))),
            "QWENPAW_UPSTREAM_REF": os.environ.get("QWENPAW_AIO_BUILD_QWENPAW_UPSTREAM_REF", os.environ.get("QWENPAW_HFS_BUILD_QWENPAW_UPSTREAM_REF", "")),
            "UV_VERSION": os.environ.get("QWENPAW_AIO_BUILD_UV_VERSION", os.environ.get("QWENPAW_HFS_BUILD_UV_VERSION", "")),
        },
        "space": {
            "space_host": os.environ.get("SPACE_HOST", ""),
            "space_id": os.environ.get("SPACE_ID", ""),
            "space_author_name": os.environ.get("SPACE_AUTHOR_NAME", ""),
        },
    }


def system_info() -> dict[str, Any]:
    usage = shutil.disk_usage("/data") if Path("/data").exists() else shutil.disk_usage("/")
    return {
        "uptime_seconds": round(time.time() - STARTED_AT, 3),
        "loadavg": os.getloadavg() if hasattr(os, "getloadavg") else None,
        "disk_data": {"total": usage.total, "used": usage.used, "free": usage.free},
        "process_count": len([p for p in Path("/proc").iterdir() if p.name.isdigit()]) if Path("/proc").exists() else None,
    }


def persistence_info() -> dict[str, Any]:
    working = Path(env("QWENPAW_WORKING_DIR", "/data/qwenpaw/working"))
    secrets = Path(env("QWENPAW_SECRET_DIR", "/data/qwenpaw/secrets"))
    backups = Path(env("QWENPAW_BACKUP_DIR", "/data/qwenpaw/backups"))
    probe = Path("/data/.qwenpaw_hfs_persistent_storage_probe")
    return {
        "ok": Path("/data").exists() and os.access("/data", os.W_OK),
        "data": {
            "path": "/data",
            "exists": Path("/data").exists(),
            "writable": os.access("/data", os.W_OK),
            "persistent_probe_exists": probe.exists(),
        },
        "qwenpaw": {
            "working_dir": str(working),
            "working_dir_exists": working.exists(),
            "config_exists": (working / "config.json").exists(),
            "secret_dir": str(secrets),
            "secret_dir_exists": secrets.exists(),
            "backup_dir": str(backups),
            "backup_dir_exists": backups.exists(),
            "backup_count": len(list(backups.glob("*"))) if backups.exists() else 0,
        },
    }


def tail_log(service: str, limit: int = 200) -> str:
    filename = LOG_WHITELIST.get(service)
    if not filename:
        raise ValueError("service is not in log whitelist")
    path = (LOG_DIR / filename).resolve()
    if not str(path).startswith(str(LOG_DIR.resolve())):
        raise ValueError("invalid log path")
    if not path.exists():
        return ""
    limit = max(1, min(limit, 1000))
    proc = subprocess.run(["tail", "-n", str(limit), str(path)], check=False, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=3)
    return proc.stdout if proc.returncode == 0 else proc.stderr


def recent_errors() -> dict[str, list[str]]:
    needles = ("error", "exception", "traceback", "failed", "fatal")
    result: dict[str, list[str]] = {}
    for service in LOG_WHITELIST:
        try:
            text = tail_log(service, 100)
        except Exception:
            continue
        matches = [line for line in text.splitlines() if any(n in line.lower() for n in needles)]
        if matches:
            result[service] = matches[-20:]
    return result


class Handler(BaseHTTPRequestHandler):
    server_version = "qwenpaw-hfs-ops/1.0"

    def log_message(self, fmt: str, *args: Any) -> None:
        return

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"

        if path in {"/_ops", "/_ops/index"}:
            if not require_auth(self):
                return
            if getattr(self, "ops_auth_source", "") == "query":
                query_token_redirect(self)
                return
            body = """
<!doctype html><html><head><meta charset='utf-8'><title>QwenPaw HFS Ops</title></head>
<body><h1>QwenPaw HFS Ops</h1><p>Read-only diagnostics dashboard.</p>
<ul>
<li><a href='/_ops/health'>health</a></li>
<li><a href='/_ops/status'>status</a></li>
<li><a href='/_ops/system'>system</a></li>
<li><a href='/_ops/persistence'>persistence</a></li>
<li><a href='/_ops/config'>config</a></li>
<li><a href='/_ops/version'>version</a></li>
<li><a href='/_ops/errors'>errors</a></li>
<li><a href='/_ops/metrics'>metrics</a></li>
</ul></body></html>
"""
            text_response(self, 200, body, "text/html; charset=utf-8")
            return

        if path in {"/healthz", "/readyz"}:
            qwenpaw_port = int(os.environ.get("QWENPAW_PORT", "8088"))
            qwenpaw_up = tcp_check("127.0.0.1", qwenpaw_port)
            body = {
                "ok": qwenpaw_up,
                "checks": {
                    "qwenpaw_tcp": qwenpaw_up,
                    "ops_tcp": True,
                    "data_writable": os.access("/data", os.W_OK),
                    "config_exists": Path(os.environ.get("QWENPAW_WORKING_DIR", "/data/qwenpaw/working"), "config.json").exists(),
                },
                "uptime_seconds": round(time.time() - STARTED_AT, 3),
            }
            json_response(self, 200 if body["ok"] else 503, body)
            return

        if path in {"/_ops/health", "/_ops/healthz", "/_ops/readyz"}:
            if not require_auth(self):
                return
            qwenpaw_port = int(os.environ.get("QWENPAW_PORT", "8088"))
            qwenpaw_up = tcp_check("127.0.0.1", qwenpaw_port)
            body = {
                "ok": qwenpaw_up,
                "checks": {
                    "qwenpaw_tcp": qwenpaw_up,
                    "ops_tcp": True,
                    "data_writable": os.access("/data", os.W_OK),
                    "config_exists": Path(os.environ.get("QWENPAW_WORKING_DIR", "/data/qwenpaw/working"), "config.json").exists(),
                },
                "uptime_seconds": round(time.time() - STARTED_AT, 3),
            }
            json_response(self, 200 if body["ok"] else 503, body)
            return

        if path == "/_ops/status":
            if not require_auth(self):
                return
            json_response(self, 200, {"ok": True, "processes": fixed_supervisor_status()})
            return

        if path == "/_ops/system":
            if not require_auth(self):
                return
            json_response(self, 200, {"ok": True, "system": system_info()})
            return

        if path == "/_ops/config":
            if not require_auth(self):
                return
            json_response(self, 200, {"ok": True, "config": safe_config()})
            return

        if path == "/_ops/persistence":
            if not require_auth(self):
                return
            body = persistence_info()
            json_response(self, 200 if body["ok"] else 503, body)
            return

        if path == "/_ops/version":
            if not require_auth(self):
                return
            json_response(self, 200, {"ok": True, "version": version_info()})
            return

        if path == "/_ops/logs":
            if not require_auth(self):
                return
            qs = parse_qs(parsed.query)
            service = (qs.get("service") or ["qwenpaw"])[0]
            limit_raw = (qs.get("limit") or ["200"])[0]
            try:
                body = tail_log(service, int(limit_raw))
            except Exception as exc:
                json_response(self, 400, {"ok": False, "error": str(exc), "allowed_services": sorted(LOG_WHITELIST)})
                return
            text_response(self, 200, body)
            return

        if path == "/_ops/errors":
            if not require_auth(self):
                return
            json_response(self, 200, {"ok": True, "errors": recent_errors()})
            return

        if path == "/_ops/metrics":
            if not require_auth(self):
                return
            qwenpaw_up = 1 if tcp_check("127.0.0.1", int(os.environ.get("QWENPAW_PORT", "8088"))) else 0
            metrics = [
                "# HELP qwenpaw_hfs_uptime_seconds Ops service uptime.",
                "# TYPE qwenpaw_hfs_uptime_seconds gauge",
                f"qwenpaw_hfs_uptime_seconds {time.time() - STARTED_AT:.3f}",
                "# HELP qwenpaw_hfs_qwenpaw_tcp_up Internal QwenPaw TCP status.",
                "# TYPE qwenpaw_hfs_qwenpaw_tcp_up gauge",
                f"qwenpaw_hfs_qwenpaw_tcp_up {qwenpaw_up}",
            ]
            text_response(self, 200, "\n".join(metrics) + "\n")
            return

        json_response(self, 404, {"ok": False, "error": "not found"})


def main() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"ops-service listening on 127.0.0.1:{PORT}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
