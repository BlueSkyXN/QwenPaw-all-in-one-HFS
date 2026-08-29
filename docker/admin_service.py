#!/usr/bin/env python3
from __future__ import annotations

import hmac
import json
import os
import subprocess
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

PORT = int(os.environ.get("QWENPAW_ADMIN_PORT", "8082"))
SUPERVISOR_CONF = os.environ.get("SUPERVISOR_CONF", "/home/user/app/docker/supervisord.conf")
AUDIT_LOG = Path(os.environ.get("QWENPAW_ADMIN_AUDIT_LOG", "/data/var/logs/admin-audit.jsonl"))
SERVICE_WHITELIST = {"qwenpaw", "nginx", "ops-service", "admin-service", "xvfb"}


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


def enabled() -> bool:
    return os.environ.get("ADMIN_ENABLED", "false").lower() in {"1", "true", "yes", "on"}


def json_response(handler: BaseHTTPRequestHandler, status: int, body: dict[str, Any]) -> None:
    payload = json.dumps(body, ensure_ascii=False, sort_keys=True).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Cache-Control", "no-store")
    add_security_headers(handler)
    handler.send_header("Content-Length", str(len(payload)))
    handler.end_headers()
    handler.wfile.write(payload)


def text_response(handler: BaseHTTPRequestHandler, status: int, body: str, content_type: str = "text/plain; charset=utf-8") -> None:
    payload = body.encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Cache-Control", "no-store")
    add_security_headers(handler)
    handler.send_header("Content-Length", str(len(payload)))
    handler.end_headers()
    handler.wfile.write(payload)


def add_security_headers(handler: BaseHTTPRequestHandler) -> None:
    handler.send_header("X-Content-Type-Options", "nosniff")
    handler.send_header("Referrer-Policy", "no-referrer")
    handler.send_header("X-Frame-Options", "DENY")
    handler.send_header("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")


def token_from(handler: BaseHTTPRequestHandler) -> str:
    token = handler.headers.get("X-Admin-Token", "")
    auth = handler.headers.get("Authorization", "")
    if not token and auth.startswith("Bearer "):
        token = auth.removeprefix("Bearer ").strip()
    return token


def require_admin(handler: BaseHTTPRequestHandler) -> bool:
    if not enabled():
        json_response(handler, 404, {"ok": False, "error": "admin disabled"})
        return False
    expected = os.environ.get("ADMIN_PASSWORD", "")
    if not expected:
        json_response(handler, 503, {"ok": False, "error": "ADMIN_PASSWORD is not configured"})
        return False
    if not hmac.compare_digest(token_from(handler), expected):
        json_response(handler, 401, {"ok": False, "error": "unauthorized"})
        return False
    return True


def audit(event: dict[str, Any]) -> None:
    try:
        AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
        event = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), **event}
        with AUDIT_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
    except OSError as exc:
        sys.stderr.write(f"admin audit write failed: {exc}\n")


def read_body(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    length = int(handler.headers.get("Content-Length", "0") or "0")
    if length > 65536:
        return {}
    raw = handler.rfile.read(length) if length else b"{}"
    try:
        return json.loads(raw.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        return {}


def require_confirm(handler: BaseHTTPRequestHandler, body: dict[str, Any]) -> bool:
    csrf_expected = os.environ.get("ADMIN_CSRF_TOKEN", "")
    if not csrf_expected:
        json_response(handler, 503, {"ok": False, "error": "ADMIN_CSRF_TOKEN is not configured"})
        return False
    if handler.headers.get("X-CSRF-Token", "") != csrf_expected:
        json_response(handler, 403, {"ok": False, "error": "valid X-CSRF-Token is required"})
        return False
    if not (body.get("confirm") is True or str(body.get("confirm", "")).lower() == "true"):
        json_response(handler, 400, {"ok": False, "error": "confirm=true is required"})
        return False
    return True


def run_fixed(args: list[str]) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(args, check=False, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15)
        return proc.returncode, proc.stdout, proc.stderr
    except FileNotFoundError as exc:
        return 127, "", str(exc)
    except subprocess.TimeoutExpired as exc:
        return 124, exc.stdout or "", f"timeout after {exc.timeout}s"


def supervisor_status() -> list[dict[str, str]]:
    rc, out, err = run_fixed(["supervisorctl", "-c", SUPERVISOR_CONF, "status"])
    lines = (out or err or "").splitlines()
    processes: list[dict[str, str]] = []
    for line in lines:
        parts = line.split(None, 2)
        if len(parts) >= 2:
            processes.append({"name": parts[0], "state": parts[1], "detail": parts[2] if len(parts) > 2 else ""})
    if not processes and rc != 0:
        processes.append({"name": "supervisor", "state": "ERROR", "detail": err.strip()})
    return processes


def status_payload() -> dict[str, Any]:
    return {
        "ok": True,
        "service": "qwenpaw-hfs-admin",
        "admin": {
            "enabled": enabled(),
            "port": PORT,
            "csrf_required": True,
            "audit_log": str(AUDIT_LOG),
        },
        "actions": {
            "allowed_services": sorted(SERVICE_WHITELIST),
            "confirm_required": True,
        },
        "supervisor": {"processes": supervisor_status()},
    }


def actions_payload() -> dict[str, Any]:
    return {
        "ok": True,
        "actions": [
            {
                "id": "restart-service",
                "method": "POST",
                "path": "/_admin/api/actions/restart-service",
                "confirm_required": True,
                "csrf_required": True,
                "allowed_services": sorted(SERVICE_WHITELIST),
            },
            {
                "id": "reload-nginx",
                "method": "POST",
                "path": "/_admin/api/actions/reload-nginx",
                "confirm_required": True,
                "csrf_required": True,
            },
            {
                "id": "run-health-checks",
                "method": "POST",
                "path": "/_admin/api/actions/run-health-checks",
                "confirm_required": True,
                "csrf_required": True,
            },
        ],
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "qwenpaw-hfs-admin/1.0"

    def log_message(self, fmt: str, *args: Any) -> None:
        return

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        if not enabled():
            json_response(self, 404, {"ok": False, "error": "admin disabled"})
            return

        if path in {"/_admin", "/_admin/index"}:
            body = """
<!doctype html><html><head><meta charset='utf-8'><title>QwenPaw HFS Admin</title></head>
<body><h1>QwenPaw HFS Admin</h1><p>Admin APIs require X-Admin-Token, X-CSRF-Token, and confirm=true.</p>
<ul>
<li>GET /_admin/api/status</li>
<li>GET /_admin/api/actions</li>
<li>GET /_admin/api/audit?limit=50</li>
</ul></body></html>
"""
            text_response(self, 200, body, "text/html; charset=utf-8")
            return

        if path == "/_admin/api/status":
            if not require_admin(self):
                return
            json_response(self, 200, status_payload())
            return

        if path == "/_admin/api/actions":
            if not require_admin(self):
                return
            json_response(self, 200, actions_payload())
            return

        if path == "/_admin/api/audit":
            if not require_admin(self):
                return
            qs = parse_qs(parsed.query)
            limit = parse_int((qs.get("limit") or ["50"])[0], 50, minimum=1, maximum=500)
            if not AUDIT_LOG.exists():
                json_response(self, 200, {"ok": True, "exists": False, "events": []})
                return
            lines = AUDIT_LOG.read_text(encoding="utf-8").splitlines()[-limit:]
            events = []
            for line in lines:
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
            json_response(self, 200, {"ok": True, "exists": True, "events": events})
            return

        json_response(self, 404, {"ok": False, "error": "not found"})

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        if not require_admin(self):
            return
        body = read_body(self)
        if not require_confirm(self, body):
            return

        if path == "/_admin/api/actions/restart-service":
            service = str(body.get("service", ""))
            if service not in SERVICE_WHITELIST:
                json_response(self, 400, {"ok": False, "error": "service not allowed", "allowed": sorted(SERVICE_WHITELIST)})
                return
            rc, out, err = run_fixed(["supervisorctl", "-c", SUPERVISOR_CONF, "restart", service])
            audit({"action": "restart-service", "service": service, "returncode": rc})
            json_response(self, 200 if rc == 0 else 500, {"ok": rc == 0, "stdout": out, "stderr": err})
            return

        if path == "/_admin/api/actions/reload-nginx":
            test_rc, test_out, test_err = run_fixed(["nginx", "-t", "-c", "/home/user/app/docker/nginx.conf"])
            if test_rc != 0:
                audit({"action": "reload-nginx", "phase": "nginx-test", "returncode": test_rc})
                json_response(self, 500, {"ok": False, "phase": "nginx-test", "stdout": test_out, "stderr": test_err})
                return
            rc, out, err = run_fixed(["supervisorctl", "-c", SUPERVISOR_CONF, "restart", "nginx"])
            audit({"action": "reload-nginx", "phase": "restart", "returncode": rc})
            json_response(self, 200 if rc == 0 else 500, {"ok": rc == 0, "phase": "restart", "stdout": out, "stderr": err})
            return

        if path == "/_admin/api/actions/run-health-checks":
            rc, out, err = run_fixed(["/home/user/app/docker/healthcheck.sh"])
            audit({"action": "run-health-checks", "returncode": rc})
            json_response(self, 200 if rc == 0 else 500, {"ok": rc == 0, "stdout": out, "stderr": err})
            return

        json_response(self, 404, {"ok": False, "error": "not found"})


def main() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"admin-service listening on 127.0.0.1:{PORT}; enabled={enabled()}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
